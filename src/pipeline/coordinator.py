"""
Pipeline Coordinator for Microstock Generator Automation (Hybrid Free-Tier Workflow).
Step 4 Production Pipeline:
- [1/5] pHash Deduplication (Local)
- [2/5] Free-Tier Vision QC & Adobe Stock SEO Metadata (Gemini Flash -> OpenRouter :free -> Local fallback)
- [3/5] AI Super-Resolution (Upscayl 4x / optional passthrough)
- [4/5] High-Precision Post-Processing (Isolated Anti-Halo PNG vs Full-Scene sRGB JPEG)
- [5/5] Technical Validation + IPTC/XMP ExifTool Embed + Adobe Stock CSV + Manifest + .txt Run Log
"""

import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional
import numpy as np
from PIL import Image, ImageOps

from .compliance import sanitize_filename
from .config import PipelineConfig, load_config
from .dedup import filter_near_duplicates
from .logger import RunLogger
from .manifest import ManifestManager, calculate_file_hash
from .metadata import MetadataEngine
from .postprocess import PostProcessor
from .qa_auditor import VisionQAAuditor
from .upscaler import UpscaylEngine
from .validator import TechnicalValidator


def classify_asset_type(image_path: Path) -> str:
    """
    Inspect the outer 2% border ring of an image to determine whether it is:
    - 'isolated': Subject on a clean near-white studio background -> Transparent PNG
    - 'scene': Full-scene / dark / textured / environmental background -> sRGB JPEG
    """
    try:
        with Image.open(image_path) as raw_img:
            img = ImageOps.exif_transpose(raw_img)
            rgb = img.convert("RGB")
            rgb.thumbnail((256, 256))
            arr = np.array(rgb)
            h, w, _ = arr.shape
            pad_y = max(2, int(h * 0.02))
            pad_x = max(2, int(w * 0.02))

            top = arr[:pad_y, :, :].reshape(-1, 3)
            bottom = arr[h - pad_y:, :, :].reshape(-1, 3)
            left = arr[:, :pad_x, :].reshape(-1, 3)
            right = arr[:, w - pad_x:, :].reshape(-1, 3)

            border = np.vstack([top, bottom, left, right])
            near_white = np.all(border >= 232, axis=1)
            white_ratio = float(np.mean(near_white))
            return "isolated" if white_ratio >= 0.75 else "scene"
    except Exception:
        return "isolated"


class PipelineCoordinator:
    def __init__(self, config: Optional[PipelineConfig] = None, run_logger: Optional[RunLogger] = None):
        self.config = config or load_config()
        self.run_logger = run_logger
        self.upscaler = UpscaylEngine(self.config)
        self.postprocessor = PostProcessor(self.config)
        self.validator = TechnicalValidator(self.config)
        self.qa_auditor = VisionQAAuditor(self.config)
        self.metadata_engine = MetadataEngine(self.config)

    def log(self, msg: str = ""):
        if self.run_logger is not None:
            self.run_logger.log(msg)
        else:
            print(msg, flush=True)

    def process_batch_folder(
        self,
        folder: Path,
        asset_type: str = "auto",
        prompt_hint: Optional[str] = None,
        custom_output_folder: Optional[Path] = None
    ) -> Dict[str, Any]:
        """
        Process a single batch folder through the full Step 4 pipeline.
        Outputs production-ready images, adobe_stock_metadata.csv, manifest.json, and .txt run log.
        """
        self.log(f"\n==================================================")
        self.log(f"🔄 Processing Folder: [{folder.name}] (Mode: {asset_type.upper()})")
        self.log(f"   Background Removal: {'ENABLED ✅' if self.config.remove_bg else 'DISABLED (Original Background Preserved) ⚪'}")
        self.log(f"   Free-Tier Vision  : {', '.join(self.qa_auditor.llm.available_vision_providers()) or 'OFFLINE FALLBACK (LocalMetadataEngine)'}")
        if self.config.bg_output_dir:
            self.log(f"   Cutouts Output    : {self.config.bg_output_dir}")
        self.log(f"==================================================")

        valid_exts = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}
        raw_folder = folder / "raw"

        # Organize loose images into raw/ if needed
        if not raw_folder.exists():
            loose_imgs = [
                f for f in folder.iterdir()
                if f.is_file() and f.suffix.lower() in valid_exts and not f.name.startswith(".")
            ]
            if loose_imgs:
                raw_folder.mkdir(parents=True, exist_ok=True)
                for img in loose_imgs:
                    shutil.move(img, raw_folder / img.name)

        raw_images = sorted([
            f for f in raw_folder.iterdir()
            if f.is_file() and f.suffix.lower() in valid_exts and not f.name.startswith(".")
        ]) if raw_folder.exists() else []

        if not raw_images:
            self.log(f"⚠️ No raw images found in '{folder.name}/raw'. Skipping.")
            return {"folder": folder.name, "passed": 0, "skipped": 0, "failed": 0, "ai_rejected": 0}

        # Resolve result folder & load manifest early for per-file incremental skipping
        if custom_output_folder:
            result_folder = custom_output_folder
        elif self.config.output_dir:
            result_folder = self.config.output_dir / folder.name
        else:
            result_folder = folder / "result"

        manifest = ManifestManager(result_folder / "manifest.json")
        raw_hashes: Dict[str, str] = {}
        pending_raw_images: List[Path] = []
        skipped_count = 0

        for img in raw_images:
            try:
                r_hash = calculate_file_hash(img)
            except Exception:
                r_hash = ""
            raw_hashes[img.stem] = r_hash

            existing_out = manifest.is_raw_already_processed(r_hash, img.stem, result_folder)
            if not existing_out and result_folder.exists():
                # Backward-compatible check for legacy results without manifest.json
                for ext in (".png", ".jpg"):
                    cand_name = sanitize_filename(img.stem, ext=ext, max_len=self.config.max_filename_chars)
                    if (result_folder / cand_name).exists():
                        existing_out = cand_name
                        break

            if existing_out:
                skipped_count += 1
                self.log(f"  ⏭️  Already in result/: {img.name} -> {existing_out} (skipping)")
            else:
                pending_raw_images.append(img)

        if not pending_raw_images:
            self.log(f"✅ All {skipped_count} raw image(s) in '{folder.name}' are already in '{result_folder.name}/'. Nothing new to process.")
            return {
                "folder": folder.name,
                "passed": 0,
                "skipped": skipped_count,
                "failed": 0,
                "ai_rejected": 0,
                "result_folder": result_folder,
            }

        # 1. Deduplication Gate (pHash)
        self.log(f"\n[1/5] Perceptual Hash Deduplication ({len(pending_raw_images)} new image(s), {skipped_count} skipped)...")
        kept_images, rejected_dups = filter_near_duplicates(
            pending_raw_images,
            threshold=self.config.dedup_phash_threshold
        )
        if rejected_dups:
            self.log(f"  ⚠️ Filtered out {len(rejected_dups)} duplicate/very similar images.")
            dup_folder = folder / "rejected_similar"
            dup_folder.mkdir(parents=True, exist_ok=True)
            for dup_img, original, dist in rejected_dups:
                shutil.move(dup_img, dup_folder / dup_img.name)
                self.log(f"   -> Moved {dup_img.name} (Hamming dist: {dist} to {original.name})")

        # Determine per-image asset type (stem -> 'isolated' or 'scene')
        image_types: Dict[str, str] = {}
        for img_path in kept_images:
            if not self.config.remove_bg:
                detected = "scene"
            else:
                detected = classify_asset_type(img_path) if asset_type == "auto" else asset_type
            image_types[img_path.stem] = detected
            self.log(f"  • {img_path.name} -> {detected.upper()}")

        # 2. Free-Tier Vision QC + Adobe Stock SEO Metadata (BEFORE Upscaling to save GPU time!)
        metadata_by_stem: Dict[str, Dict[str, Any]] = {}
        ai_rejected_count = 0
        qa_passed_images: List[Path] = []
        rejected_ai_folder = folder / "rejected_ai_qa"

        if self.config.enable_ai_qa or self.config.enable_vision_metadata:
            self.log(f"\n[2/5] Free-Tier Vision QC & SEO Metadata ({len(kept_images)} images)...")
            for idx, img_path in enumerate(kept_images, start=1):
                img_type = image_types.get(img_path.stem, "scene")
                meta_res = self.qa_auditor.audit_and_generate_metadata(
                    img_path,
                    asset_type=img_type,
                    prompt_hint=prompt_hint or folder.name,
                    log_callback=self.log,
                )
                if self.config.enable_ai_qa and not meta_res["passed"]:
                    ai_rejected_count += 1
                    rejected_ai_folder.mkdir(parents=True, exist_ok=True)
                    shutil.move(img_path, rejected_ai_folder / img_path.name)
                    self.log(
                        f"  ❌ AI QC REJECTED [{idx}/{len(kept_images)}]: {img_path.name} "
                        f"(score={meta_res['score']}, provider={meta_res['provider']}) -> {meta_res['detected_issues'] or meta_res['reasons']}"
                    )
                    continue

                metadata_by_stem[img_path.stem] = meta_res
                qa_passed_images.append(img_path)
                self.log(
                    f"  ✅ QC+SEO [{idx}/{len(kept_images)}]: {img_path.name} "
                    f"(score={meta_res['score']}, provider={meta_res['provider']}) | Title: \"{meta_res['title']}\""
                )
        else:
            self.log("\n[2/5] Vision QC & SEO Metadata skipped (--skip-ai-qa). Using offline LocalMetadataEngine...")
            for img_path in kept_images:
                img_type = image_types.get(img_path.stem, "scene")
                local_meta = self.metadata_engine.generate_metadata_for_image(
                    img_path, prompt_hint=prompt_hint or folder.name, asset_type=img_type
                )
                out_ext = ".png" if img_type == "isolated" else ".jpg"
                local_meta["suggested_filename"] = sanitize_filename(
                    img_path.stem, ext=out_ext, max_len=self.config.max_filename_chars
                )
                local_meta["provider"] = "offline_local_metadata"
                metadata_by_stem[img_path.stem] = local_meta
                qa_passed_images.append(img_path)

        if not qa_passed_images:
            self.log("⚠️ No images passed AI Quality Control. Skipping upscaling and export.")
            return {
                "folder": folder.name,
                "passed": 0,
                "skipped": skipped_count,
                "failed": len(pending_raw_images),
                "ai_rejected": ai_rejected_count,
            }

        # 3. Upscale (Upscayl CLI) or Passthrough
        upscaled_folder = folder / "upscaled"
        upscaled_folder.mkdir(parents=True, exist_ok=True)

        can_upscale = self.upscaler.verify_binary() and not self.config.skip_upscale

        if not can_upscale:
            if self.config.skip_upscale:
                self.log("\n[3/5] Upscaling skipped (--skip-upscale). Passing images directly to post-processing...")
            else:
                self.log("\n[3/5] ⚠️ Upscayl binary not found. Passing images directly to post-processing...")
            for img in qa_passed_images:
                shutil.copy2(img, upscaled_folder / img.name)
        else:
            for group_type in ("isolated", "scene"):
                group_imgs = [p for p in qa_passed_images if image_types.get(p.stem) == group_type]
                if not group_imgs:
                    continue

                model_name = self.upscaler.get_model_for_type(group_type)
                self.log(f"\n[3/5] AI Super-Resolution 4x [{group_type.upper()}] ({len(group_imgs)} images via {model_name})...")

                temp_upscale_in = folder / f"_temp_{group_type}"
                temp_upscale_in.mkdir(parents=True, exist_ok=True)
                for img in group_imgs:
                    shutil.copy2(img, temp_upscale_in / img.name)

                upscale_ok = self.upscaler.upscale_folder(
                    temp_upscale_in,
                    upscaled_folder,
                    model_name=model_name,
                    scale=self.config.upscale_scale,
                    log_callback=self.log
                )
                shutil.rmtree(temp_upscale_in, ignore_errors=True)

                if not upscale_ok:
                    self.log(f"⚠️ Upscaling failed for {group_type} group. Falling back to copying raw images.")
                    for img in group_imgs:
                        shutil.copy2(img, upscaled_folder / img.name)

        # 4. Post-Processing
        result_folder.mkdir(parents=True, exist_ok=True)
        if self.config.bg_output_dir:
            self.config.bg_output_dir.mkdir(parents=True, exist_ok=True)

        self.log(f"\n[4/5] High-Precision Post-Processing -> {result_folder}...")

        active_stems = {p.stem for p in qa_passed_images}
        upscaled_files = sorted([
            f for f in (
                list(upscaled_folder.glob("*.png"))
                + list(upscaled_folder.glob("*.jpg"))
                + list(upscaled_folder.glob("*.jpeg"))
            )
            if f.stem in active_stems
        ])
        processed_items: List[tuple] = []

        for idx, up_file in enumerate(upscaled_files, start=1):
            orig_stem = up_file.stem
            if not self.config.remove_bg:
                img_type = "scene"
            else:
                img_type = image_types.get(orig_stem, "isolated" if asset_type == "auto" else asset_type)

            out_ext = ".png" if img_type == "isolated" else ".jpg"
            meta = metadata_by_stem.get(orig_stem, {})
            preferred_name = meta.get("suggested_filename") or sanitize_filename(
                orig_stem, ext=out_ext, max_len=self.config.max_filename_chars
            )
            # Ensure extension matches final output type
            preferred_stem = Path(preferred_name).stem
            clean_filename = sanitize_filename(preferred_stem, ext=out_ext, max_len=self.config.max_filename_chars)
            target_out = result_folder / clean_filename

            # Handle name collisions if multiple files sanitize to identical stems
            collision_idx = 1
            while target_out.exists():
                suffix = f"_{collision_idx}"
                stem_len = self.config.max_filename_chars - len(out_ext) - len(suffix)
                safe_stem = sanitize_filename(preferred_stem, ext="", max_len=stem_len).rstrip("_-")
                target_out = result_folder / f"{safe_stem}{suffix}{out_ext}"
                collision_idx += 1

            if img_type == "isolated":
                ok, err = self.postprocessor.process_isolated_png(up_file, target_out, log_callback=self.log)
                if ok and self.config.bg_output_dir:
                    shutil.copy2(target_out, self.config.bg_output_dir / target_out.name)
            else:
                ok, err = self.postprocessor.process_scene_jpeg(up_file, target_out, log_callback=self.log)

            if ok:
                processed_items.append((target_out, img_type, orig_stem, meta))
                self.log(f"  • Processed [{idx}/{len(upscaled_files)}] ({img_type.upper()}): {target_out.name} ✅")
            else:
                self.log(f"  ❌ Post-processing failed on {up_file.name}: {err}")

        # 5. Technical Validation + Metadata Embedding + CSV Export + Manifest
        self.log(f"\n[5/5] Technical Validation, Metadata Embedding & CSV Export...")
        passed_records: List[Dict[str, Any]] = []
        csv_rows: List[Dict[str, Any]] = []
        rejected_qa_folder = folder / "rejected_qa"
        exiftool_available = self.config.embed_iptc_metadata and MetadataEngine.has_exiftool()

        if self.config.embed_iptc_metadata and not exiftool_available:
            self.log("  ℹ️ ExifTool not installed on PATH — skipping inline IPTC/XMP embed (CSV export still active).")

        for final_path, img_type, orig_stem, meta in processed_items:
            val_res = self.validator.validate_asset(final_path, asset_type=img_type)
            if not val_res["is_valid"]:
                self.log(f"  ❌ Validation FAILED for {final_path.name}: {val_res['errors']}")
                rejected_qa_folder.mkdir(parents=True, exist_ok=True)
                shutil.move(final_path, rejected_qa_folder / final_path.name)
                continue

            title = meta.get("title", "")
            keywords = meta.get("keywords", [])
            category_id = meta.get("category_id", 8)

            if exiftool_available and title:
                embedded = MetadataEngine.embed_iptc_xmp_exiftool(
                    final_path, title=title, keywords=keywords, log_callback=self.log
                )
                if embedded:
                    self.log(f"     🏷️  IPTC/XMP embedded into {final_path.name}")

            csv_rows.append({
                "filename": final_path.name,
                "title": title,
                "keywords": keywords,
                "category_id": category_id,
                "releases": "",
            })

            try:
                f_hash = calculate_file_hash(final_path)
                manifest.record_asset(
                    file_hash=f_hash,
                    original_name=orig_stem,
                    output_name=final_path.name,
                    asset_type=img_type,
                    dimensions=(val_res["stats"].get("width", 0), val_res["stats"].get("height", 0)),
                    megapixels=val_res["stats"].get("megapixels", 0.0),
                    file_size_mb=val_res["stats"].get("file_size_mb", 0.0),
                    prompt=prompt_hint or folder.name,
                    title=title,
                    keywords=keywords,
                    category_id=category_id,
                    raw_hash=raw_hashes.get(orig_stem, ""),
                )
            except Exception:
                pass

            self.log(
                f"  ✅ READY: {final_path.name} ({val_res['stats'].get('megapixels')} MP, "
                f"{val_res['stats'].get('file_size_mb')} MB) | Cat #{category_id} | {len(keywords)} kw"
            )
            if val_res["warnings"]:
                for w in val_res["warnings"]:
                    self.log(f"     ⚠️ {w}")

            passed_records.append(val_res)

        csv_path = None
        if self.config.export_csv and csv_rows:
            csv_path = result_folder / "adobe_stock_metadata.csv"
            MetadataEngine.export_adobe_csv(csv_rows, csv_path)
            self.log(f"\n📄 Adobe Stock Metadata CSV exported to: {csv_path}")

        self.log(f"\n🎉 Finished! {len(passed_records)} production-ready images saved to: {result_folder}")

        return {
            "folder": folder.name,
            "passed": len(passed_records),
            "skipped": skipped_count,
            "failed": len(pending_raw_images) - len(passed_records),
            "ai_rejected": ai_rejected_count,
            "result_folder": result_folder,
            "csv_path": csv_path,
        }

    def print_submission_checklist(self):
        """Prints a high-visibility reminder of the Adobe Stock Contributor upload requirements."""
        self.log("\n==================================================")
        self.log("📋 ADOBE STOCK SUBMISSION CHECKLIST (MANDATORY)")
        self.log("==================================================")
        self.log("When uploading to https://contributor.stock.adobe.com/:")
        self.log(" 1. 📄 Upload 'adobe_stock_metadata.csv' to auto-fill Title, Keywords & Category.")
        self.log(" 2. ☑️ Check: 'Created using generative AI tools' (MANDATORY for AI assets)")
        self.log(" 3. ☑️ Check: 'People and Property are fictional' (If depicting fictional subjects)")
        self.log(" 4. 🔍 Inspect at 100% zoom before clicking 'Submit for Review'.")
        self.log("==================================================\n")
