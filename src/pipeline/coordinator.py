"""
Pipeline Coordinator for Microstock Generator Automation (Hybrid Free-Tier Workflow).
Step 4 Production Pipeline (Resilient & Stage-Resumable):
- [1/5] pHash Deduplication (Local)
- [2/5] Free-Tier Vision QC & Adobe Stock SEO Metadata (cached per asset in .pipeline_cache.json)
- [3/5] AI Super-Resolution (Upscayl 4x / skips already-upscaled files on retry)
- [4/5] High-Precision Post-Processing (Isolated Anti-Halo PNG vs Full-Scene sRGB JPEG)
- [5/5] Technical Validation + IPTC/XMP ExifTool Embed + Incremental Adobe Stock CSV + Manifest + Reconciliation
"""

import json
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

RESULT_EXTS = (".png", ".jpg", ".jpeg")


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


def _load_stage_cache(cache_path: Path) -> Dict[str, Any]:
    if cache_path.exists():
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {"meta_by_stem": {}}


def _save_stage_cache(cache_path: Path, data: Dict[str, Any]):
    temp_file = cache_path.with_suffix(".tmp")
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temp_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        temp_file.replace(cache_path)
    except Exception:
        if temp_file.exists():
            temp_file.unlink(missing_ok=True)


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

    def _find_cached_meta_for_result(
        self,
        res_file: Path,
        stage_cache: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        meta_by_stem = stage_cache.get("meta_by_stem", {})
        ext = res_file.suffix.lower()
        for stem, entry in meta_by_stem.items():
            if entry.get("suggested_filename") == res_file.name:
                return entry
            if sanitize_filename(stem, ext=ext, max_len=self.config.max_filename_chars) == res_file.name:
                return entry
        return None

    def _reconcile_result_metadata_and_csv(
        self,
        folder: Path,
        result_folder: Path,
        manifest: ManifestManager,
        stage_cache: Dict[str, Any],
        prompt_hint: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Ensure every existing asset in result_folder has complete metadata, IPTC/XMP,
        manifest entry, and row in adobe_stock_metadata.csv — without re-upscaling or
        re-postprocessing. Also prunes stale CSV rows for files deleted by the user.
        """
        csv_path = result_folder / "adobe_stock_metadata.csv"
        if not result_folder.exists():
            return {"reconciled": 0, "csv_path": None}

        existing_result_files = sorted([
            f for f in result_folder.iterdir()
            if f.is_file() and f.suffix.lower() in RESULT_EXTS and not f.name.startswith(".")
        ])
        valid_filenames = {f.name for f in existing_result_files}
        existing_csv = MetadataEngine.load_csv_filenames(csv_path)
        stale_csv_rows = [fn for fn in existing_csv if fn not in valid_filenames]

        if not existing_result_files:
            if self.config.export_csv and csv_path.exists() and stale_csv_rows:
                MetadataEngine.export_adobe_csv([], csv_path, valid_filenames=set())
            return {"reconciled": 0, "csv_path": csv_path if csv_path.exists() else None}

        exiftool_available = self.config.embed_iptc_metadata and MetadataEngine.has_exiftool()
        rows_to_export: List[Dict[str, Any]] = []
        reconciled_count = 0

        for res_file in existing_result_files:
            if not res_file.exists():
                self.log(f"  ⏭️  Skipping missing result asset during recovery: {res_file.name}")
                continue

            img_type = "isolated" if res_file.suffix.lower() == ".png" else "scene"
            csv_row = existing_csv.get(res_file.name, {})
            man_rec = manifest.get_record_by_output_name(res_file.name)
            has_csv = bool(str(csv_row.get("Title", "")).strip() and str(csv_row.get("Keywords", "")).strip())
            has_man = bool(man_rec and man_rec.get("title") and man_rec.get("keywords"))

            if has_csv and has_man:
                continue

            try:
                title = ""
                keywords: List[str] = []
                category_id = 8
                orig_stem = res_file.stem
                raw_hash = ""

                if has_man and man_rec:
                    title = str(man_rec.get("title", "")).strip()
                    keywords = list(man_rec.get("keywords", []))
                    category_id = int(man_rec.get("category_id", 8))
                    orig_stem = str(man_rec.get("original_name", res_file.stem))
                    raw_hash = str(man_rec.get("raw_hash", ""))
                else:
                    cached = self._find_cached_meta_for_result(res_file, stage_cache)
                    if cached and cached.get("title") and cached.get("keywords"):
                        title = str(cached["title"]).strip()
                        keywords = list(cached["keywords"])
                        category_id = int(cached.get("category_id", 8))
                        raw_hash = str(cached.get("raw_hash", ""))
                    elif self.config.enable_vision_metadata:
                        self.log(f"  🔧 Recovering Vision SEO metadata for existing result: {res_file.name}...")
                        meta_res = self.qa_auditor.audit_and_generate_metadata(
                            res_file,
                            asset_type=img_type,
                            prompt_hint=prompt_hint or folder.name,
                            log_callback=self.log,
                        )
                        title = str(meta_res.get("title", "")).strip()
                        keywords = list(meta_res.get("keywords", []))
                        category_id = int(meta_res.get("category_id", 8))
                    else:
                        self.log(f"  🔧 Recovering offline metadata for existing result: {res_file.name}...")
                        local_meta = self.metadata_engine.generate_metadata_for_image(
                            res_file,
                            prompt_hint=prompt_hint or folder.name,
                            asset_type=img_type,
                        )
                        title = str(local_meta.get("title", "")).strip()
                        keywords = list(local_meta.get("keywords", []))
                        category_id = int(local_meta.get("category_id", 8))

                if not res_file.exists():
                    self.log(f"  ⏭️  Skipping missing result asset during recovery: {res_file.name}")
                    continue

                if exiftool_available and title and not has_man:
                    MetadataEngine.embed_iptc_xmp_exiftool(
                        res_file, title=title, keywords=keywords, log_callback=self.log
                    )

                val_res = self.validator.validate_asset(res_file, asset_type=img_type)
                if val_res.get("missing"):
                    self.log(f"  ⏭️  Skipping missing result asset during recovery: {res_file.name}")
                    continue

                if not has_man:
                    f_hash = calculate_file_hash(res_file)
                    manifest.record_asset(
                        file_hash=f_hash,
                        original_name=orig_stem,
                        output_name=res_file.name,
                        asset_type=img_type,
                        dimensions=(val_res["stats"].get("width", 0), val_res["stats"].get("height", 0)),
                        megapixels=val_res["stats"].get("megapixels", 0.0),
                        file_size_mb=val_res["stats"].get("file_size_mb", 0.0),
                        prompt=prompt_hint or folder.name,
                        title=title,
                        keywords=keywords,
                        category_id=category_id,
                        raw_hash=raw_hash,
                    )

                rows_to_export.append({
                    "filename": res_file.name,
                    "title": title,
                    "keywords": keywords,
                    "category_id": category_id,
                    "releases": "",
                })
                reconciled_count += 1
                self.log(f"  🔧 Reconciled metadata/CSV for existing result: {res_file.name} ✅")

            except FileNotFoundError:
                self.log(f"  ⏭️  Skipping missing result asset during recovery: {res_file.name}")
                continue

        # Recompute active valid filenames after any removals during recovery
        valid_filenames = {
            f.name for f in existing_result_files
            if f.exists()
        }

        if self.config.export_csv and (rows_to_export or stale_csv_rows or (valid_filenames and not csv_path.exists())):
            MetadataEngine.export_adobe_csv(rows_to_export, csv_path, valid_filenames=valid_filenames)
            self.log(f"\n📄 Adobe Stock Metadata CSV synced ({len(valid_filenames)} active asset(s)): {csv_path}")

        return {
            "reconciled": reconciled_count,
            "csv_path": csv_path if csv_path.exists() else None,
        }

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
        Resilient to manually deleted files and resumable on mid-run retries.
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

        # Resolve result folder & load manifest/cache early for per-file incremental skipping & recovery
        if custom_output_folder:
            result_folder = custom_output_folder
        elif self.config.output_dir:
            result_folder = self.config.output_dir / folder.name
        else:
            result_folder = folder / "result"

        manifest = ManifestManager(result_folder / "manifest.json")
        cache_path = folder / ".pipeline_cache.json"
        stage_cache = _load_stage_cache(cache_path)

        # Organize loose images into raw/ if needed
        if not raw_folder.exists():
            loose_imgs = [
                f for f in folder.iterdir()
                if f.is_file() and f.suffix.lower() in valid_exts and not f.name.startswith(".")
            ]
            if loose_imgs:
                raw_folder.mkdir(parents=True, exist_ok=True)
                for img in loose_imgs:
                    if img.exists():
                        shutil.move(img, raw_folder / img.name)

        raw_images = sorted([
            f for f in raw_folder.iterdir()
            if f.is_file() and f.suffix.lower() in valid_exts and not f.name.startswith(".")
        ]) if raw_folder.exists() else []

        if not raw_images:
            rec_res = self._reconcile_result_metadata_and_csv(
                folder, result_folder, manifest, stage_cache, prompt_hint
            )
            if rec_res["reconciled"] == 0:
                self.log(f"⚠️ No raw images found in '{folder.name}/raw'. Skipping.")
            return {
                "folder": folder.name,
                "passed": 0,
                "skipped": 0,
                "reconciled": rec_res["reconciled"],
                "failed": 0,
                "ai_rejected": 0,
                "result_folder": result_folder,
                "csv_path": rec_res["csv_path"],
            }

        raw_hashes: Dict[str, str] = {}
        pending_raw_images: List[Path] = []
        skipped_count = 0

        for img in raw_images:
            if not img.exists():
                continue
            try:
                r_hash = calculate_file_hash(img)
            except FileNotFoundError:
                self.log(f"  ⏭️  Skipping missing raw asset: {img.name}")
                continue
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
            rec_res = self._reconcile_result_metadata_and_csv(
                folder, result_folder, manifest, stage_cache, prompt_hint
            )
            self.log(f"✅ All {skipped_count} raw image(s) in '{folder.name}' are already in '{result_folder.name}/'. Nothing new to process.")
            return {
                "folder": folder.name,
                "passed": 0,
                "skipped": skipped_count,
                "reconciled": rec_res["reconciled"],
                "failed": 0,
                "ai_rejected": 0,
                "result_folder": result_folder,
                "csv_path": rec_res["csv_path"],
            }

        # 1. Deduplication Gate (pHash)
        pending_raw_images = [p for p in pending_raw_images if p.exists()]
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
                if dup_img.exists():
                    shutil.move(dup_img, dup_folder / dup_img.name)
                    self.log(f"   -> Moved {dup_img.name} (Hamming dist: {dist} to {original.name})")

        # Determine per-image asset type (stem -> 'isolated' or 'scene')
        image_types: Dict[str, str] = {}
        existing_kept: List[Path] = []
        for img_path in kept_images:
            if not img_path.exists():
                self.log(f"  ⏭️  Skipping missing raw asset: {img_path.name}")
                continue
            if not self.config.remove_bg:
                detected = "scene"
            else:
                detected = classify_asset_type(img_path) if asset_type == "auto" else asset_type
            image_types[img_path.stem] = detected
            existing_kept.append(img_path)
            self.log(f"  • {img_path.name} -> {detected.upper()}")
        kept_images = existing_kept

        # 2. Free-Tier Vision QC + Adobe Stock SEO Metadata (cached per stem for stage-resumable retry)
        metadata_by_stem: Dict[str, Dict[str, Any]] = {}
        cached_meta = stage_cache.setdefault("meta_by_stem", {})
        ai_rejected_count = 0
        qa_passed_images: List[Path] = []
        rejected_ai_folder = folder / "rejected_ai_qa"

        if self.config.enable_ai_qa or self.config.enable_vision_metadata:
            self.log(f"\n[2/5] Free-Tier Vision QC & SEO Metadata ({len(kept_images)} images)...")
            for idx, img_path in enumerate(kept_images, start=1):
                if not img_path.exists():
                    self.log(f"  ⏭️  Skipping missing raw asset [{idx}/{len(kept_images)}]: {img_path.name}")
                    continue

                img_type = image_types.get(img_path.stem, "scene")
                r_hash = raw_hashes.get(img_path.stem, "")
                cached_entry = cached_meta.get(img_path.stem)

                if (
                    cached_entry
                    and cached_entry.get("raw_hash") == r_hash
                    and cached_entry.get("title")
                    and cached_entry.get("asset_type") == img_type
                ):
                    meta_res = dict(cached_entry)
                    self.log(f"  ♻️  Reusing cached QC+SEO [{idx}/{len(kept_images)}]: {img_path.name} ✅")
                else:
                    self.log(f"  🔎 [{idx}/{len(kept_images)}] Inspecting '{img_path.name}' ({img_type.upper()})...")
                    try:
                        meta_res = self.qa_auditor.audit_and_generate_metadata(
                            img_path,
                            asset_type=img_type,
                            prompt_hint=prompt_hint or folder.name,
                            log_callback=self.log,
                        )
                    except FileNotFoundError:
                        self.log(f"  ⏭️  Skipping missing raw asset: {img_path.name}")
                        continue

                    cached_meta[img_path.stem] = {
                        **meta_res,
                        "asset_type": img_type,
                        "raw_hash": r_hash,
                    }
                    _save_stage_cache(cache_path, stage_cache)

                if self.config.enable_ai_qa and not meta_res.get("passed", True):
                    ai_rejected_count += 1
                    rejected_ai_folder.mkdir(parents=True, exist_ok=True)
                    if img_path.exists():
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
                    f"(score={meta_res['score']}, provider={meta_res['provider']}, "
                    f"cat=#{meta_res.get('category_id', 8)}, kw={len(meta_res.get('keywords', []))}) "
                    f"| Title: \"{meta_res['title']}\""
                )
        else:
            self.log("\n[2/5] Vision QC & SEO Metadata skipped (--skip-ai-qa). Using offline LocalMetadataEngine...")
            for img_path in kept_images:
                if not img_path.exists():
                    self.log(f"  ⏭️  Skipping missing raw asset: {img_path.name}")
                    continue
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
                cached_meta[img_path.stem] = {
                    **local_meta,
                    "asset_type": img_type,
                    "raw_hash": raw_hashes.get(img_path.stem, ""),
                }
                qa_passed_images.append(img_path)
            _save_stage_cache(cache_path, stage_cache)

        qa_passed_images = [p for p in qa_passed_images if p.exists()]
        if not qa_passed_images:
            self.log("⚠️ No images passed AI Quality Control. Skipping upscaling and export.")
            rec_res = self._reconcile_result_metadata_and_csv(
                folder, result_folder, manifest, stage_cache, prompt_hint
            )
            return {
                "folder": folder.name,
                "passed": 0,
                "skipped": skipped_count,
                "reconciled": rec_res["reconciled"],
                "failed": len(pending_raw_images),
                "ai_rejected": ai_rejected_count,
                "result_folder": result_folder,
                "csv_path": rec_res["csv_path"],
            }

        # 3. Upscale (Upscayl CLI) or Passthrough — skips images already in upscaled/
        upscaled_folder = folder / "upscaled"
        upscaled_folder.mkdir(parents=True, exist_ok=True)

        can_upscale = self.upscaler.verify_binary() and not self.config.skip_upscale
        imgs_needing_upscale: List[Path] = []

        for img in qa_passed_images:
            if not img.exists():
                self.log(f"  ⏭️  Skipping missing raw asset before upscale: {img.name}")
                continue
            existing_up = None
            for cand in (upscaled_folder / f"{img.stem}.png", upscaled_folder / img.name):
                if cand.is_file() and cand.stat().st_size > 0:
                    existing_up = cand
                    break
            if existing_up is not None:
                self.log(f"  ♻️  Reusing existing upscaled file: {existing_up.name}")
            else:
                imgs_needing_upscale.append(img)

        if not imgs_needing_upscale:
            self.log("\n[3/5] All passed images already present in upscaled/. Skipping upscaling...")
        elif not can_upscale:
            if self.config.skip_upscale:
                self.log("\n[3/5] Upscaling skipped (--skip-upscale). Passing images directly to post-processing...")
            else:
                self.log("\n[3/5] ⚠️ Upscayl binary not found. Passing images directly to post-processing...")
            for img in imgs_needing_upscale:
                if img.exists():
                    shutil.copy2(img, upscaled_folder / img.name)
        else:
            for group_type in ("isolated", "scene"):
                group_imgs = [p for p in imgs_needing_upscale if image_types.get(p.stem) == group_type and p.exists()]
                if not group_imgs:
                    continue

                model_name = self.upscaler.get_model_for_type(group_type)
                self.log(f"\n[3/5] AI Super-Resolution 4x [{group_type.upper()}] ({len(group_imgs)} images via {model_name})...")

                temp_upscale_in = folder / f"_temp_{group_type}"
                temp_upscale_in.mkdir(parents=True, exist_ok=True)
                for img in group_imgs:
                    if img.exists():
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
                        if img.exists():
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
            if not up_file.exists():
                self.log(f"  ⏭️  Skipping missing upscaled file [{idx}/{len(upscaled_files)}]: {up_file.name}")
                continue

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
            preferred_stem = Path(preferred_name).stem
            clean_filename = sanitize_filename(preferred_stem, ext=out_ext, max_len=self.config.max_filename_chars)
            target_out = result_folder / clean_filename

            # Reuse existing unrecorded result asset from an interrupted previous run
            if (
                target_out.exists()
                and target_out.stat().st_size > 0
                and manifest.get_record_by_output_name(target_out.name) is None
            ):
                processed_items.append((target_out, img_type, orig_stem, meta))
                self.log(f"  ♻️  Reusing existing result asset [{idx}/{len(upscaled_files)}]: {target_out.name} ✅")
                continue

            # Handle name collisions if multiple files sanitize to identical stems
            collision_idx = 1
            while target_out.exists():
                suffix = f"_{collision_idx}"
                stem_len = self.config.max_filename_chars - len(out_ext) - len(suffix)
                safe_stem = sanitize_filename(preferred_stem, ext="", max_len=stem_len).rstrip("_-")
                target_out = result_folder / f"{safe_stem}{suffix}{out_ext}"
                collision_idx += 1

            try:
                if img_type == "isolated":
                    ok, err = self.postprocessor.process_isolated_png(up_file, target_out, log_callback=self.log)
                    if ok and self.config.bg_output_dir and target_out.exists():
                        shutil.copy2(target_out, self.config.bg_output_dir / target_out.name)
                else:
                    ok, err = self.postprocessor.process_scene_jpeg(up_file, target_out, log_callback=self.log)
            except FileNotFoundError:
                self.log(f"  ⏭️  Skipping missing upscaled file during post-processing: {up_file.name}")
                continue

            if ok:
                processed_items.append((target_out, img_type, orig_stem, meta))
                self.log(f"  • Processed [{idx}/{len(upscaled_files)}] ({img_type.upper()}): {target_out.name} ✅")
            else:
                self.log(f"  ❌ Post-processing failed on {up_file.name}: {err}")

        # 5. Technical Validation + Metadata Embedding + Incremental CSV Export + Manifest
        self.log(f"\n[5/5] Technical Validation, Metadata Embedding & CSV Export...")
        passed_records: List[Dict[str, Any]] = []
        rejected_qa_folder = folder / "rejected_qa"
        exiftool_available = self.config.embed_iptc_metadata and MetadataEngine.has_exiftool()
        csv_path: Optional[Path] = result_folder / "adobe_stock_metadata.csv"

        if self.config.embed_iptc_metadata and not exiftool_available:
            self.log("  ℹ️ ExifTool not installed on PATH — skipping inline IPTC/XMP embed (CSV export still active).")

        for final_path, img_type, orig_stem, meta in processed_items:
            if not final_path.exists():
                self.log(f"  ⏭️  Skipping missing result asset (removed during run): {final_path.name}")
                manifest.mark_raw_removed(raw_hashes.get(orig_stem, ""), orig_stem, final_path.name)
                continue

            try:
                val_res = self.validator.validate_asset(final_path, asset_type=img_type)
                if val_res.get("missing"):
                    self.log(f"  ⏭️  Skipping missing result asset (removed during run): {final_path.name}")
                    manifest.mark_raw_removed(raw_hashes.get(orig_stem, ""), orig_stem, final_path.name)
                    continue

                if not val_res["is_valid"]:
                    self.log(f"  ❌ Validation FAILED for {final_path.name}: {val_res['errors']}")
                    rejected_qa_folder.mkdir(parents=True, exist_ok=True)
                    if final_path.exists():
                        shutil.move(final_path, rejected_qa_folder / final_path.name)
                    continue

                title = meta.get("title", "")
                keywords = meta.get("keywords", [])
                category_id = meta.get("category_id", 8)

                if exiftool_available and title and final_path.exists():
                    embedded = MetadataEngine.embed_iptc_xmp_exiftool(
                        final_path, title=title, keywords=keywords, log_callback=self.log
                    )
                    if embedded:
                        self.log(f"     🏷️  IPTC/XMP embedded into {final_path.name}")

                if not final_path.exists():
                    self.log(f"  ⏭️  Skipping missing result asset (removed before metadata save): {final_path.name}")
                    manifest.mark_raw_removed(raw_hashes.get(orig_stem, ""), orig_stem, final_path.name)
                    continue

                row = {
                    "filename": final_path.name,
                    "title": title,
                    "keywords": keywords,
                    "category_id": category_id,
                    "releases": "",
                }

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

                if self.config.export_csv:
                    MetadataEngine.export_adobe_csv([row], csv_path)

                self.log(
                    f"  ✅ READY: {final_path.name} ({val_res['stats'].get('megapixels')} MP, "
                    f"{val_res['stats'].get('file_size_mb')} MB) | Cat #{category_id} | {len(keywords)} kw"
                )
                if val_res["warnings"]:
                    for w in val_res["warnings"]:
                        self.log(f"     ⚠️ {w}")

                passed_records.append(val_res)

            except FileNotFoundError:
                self.log(f"  ⏭️  Skipping missing result asset (removed during run): {final_path.name}")
                manifest.mark_raw_removed(raw_hashes.get(orig_stem, ""), orig_stem, final_path.name)
                continue

        # Final reconciliation: recover any missing metadata/CSV & prune any deleted files from CSV
        rec_res = self._reconcile_result_metadata_and_csv(
            folder, result_folder, manifest, stage_cache, prompt_hint
        )
        final_csv = rec_res["csv_path"] if rec_res["csv_path"] else (csv_path if csv_path.exists() else None)

        self.log(f"\n🎉 Finished! {len(passed_records)} new + {rec_res['reconciled']} recovered asset(s) ready in: {result_folder}")

        return {
            "folder": folder.name,
            "passed": len(passed_records),
            "skipped": skipped_count,
            "reconciled": rec_res["reconciled"],
            "failed": max(0, len(pending_raw_images) - len(passed_records)),
            "ai_rejected": ai_rejected_count,
            "result_folder": result_folder,
            "csv_path": final_csv,
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
