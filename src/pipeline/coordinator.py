"""
Pipeline Coordinator for Microstock Generator Automation.
100% Local, Fast, and Production-Ready (Image Output Only — No CSV/JSON):
- Cross-Platform (Linux, macOS, Windows)
- Per-Image Smart Classification (Auto-detect Isolated PNG vs Full-Scene JPEG)
- Optional Background Removal & Dedicated Cutout Output Option
- pHash Deduplication (Local)
- AI Super-Resolution (Upscayl 4x / optional passthrough)
- 5-Stage Edge-Perfection Post-Processing
- Strict Technical Validation (< 45 MB, 4-100 MP, Filename <= 30 chars)
"""

import shutil
from pathlib import Path
from typing import List, Dict, Any, Optional
import numpy as np
from PIL import Image, ImageOps

from .config import PipelineConfig, load_config
from .dedup import filter_near_duplicates
from .upscaler import UpscaylEngine
from .postprocess import PostProcessor
from .validator import TechnicalValidator
from .compliance import sanitize_filename


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
    def __init__(self, config: Optional[PipelineConfig] = None):
        self.config = config or load_config()
        self.upscaler = UpscaylEngine(self.config)
        self.postprocessor = PostProcessor(self.config)
        self.validator = TechnicalValidator(self.config)

    def log(self, msg: str = ""):
        print(msg, flush=True)

    def process_batch_folder(
        self,
        folder: Path,
        asset_type: str = "auto",
        prompt_hint: Optional[str] = None,
        custom_output_folder: Optional[Path] = None
    ) -> Dict[str, Any]:
        """
        Process a single batch folder through the entire local pipeline.
        Outputs ONLY validated, production-ready images (no CSV or JSON).
        """
        self.log(f"\n==================================================")
        self.log(f"🔄 Processing Folder: [{folder.name}] (Mode: {asset_type.upper()})")
        self.log(f"   Background Removal: {'ENABLED ✅' if self.config.remove_bg else 'DISABLED (Original Background Preserved) ⚪'}")
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
            return {"folder": folder.name, "passed": 0, "failed": 0}

        # 1. Deduplication Gate (pHash)
        self.log(f"\n[1/4] Perceptual Hash Deduplication ({len(raw_images)} images)...")
        kept_images, rejected_dups = filter_near_duplicates(
            raw_images,
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
                # If remove_bg is disabled, treat all images as scenes (keeping original background)
                detected = "scene"
            else:
                detected = classify_asset_type(img_path) if asset_type == "auto" else asset_type
            image_types[img_path.stem] = detected
            self.log(f"  • {img_path.name} -> {detected.upper()}")

        # 2. Upscale (Upscayl CLI) or Passthrough
        upscaled_folder = folder / "upscaled"
        upscaled_folder.mkdir(parents=True, exist_ok=True)

        can_upscale = self.upscaler.verify_binary() and not self.config.skip_upscale

        if not can_upscale:
            if self.config.skip_upscale:
                self.log("\n[2/4] Upscaling skipped (--skip-upscale). Passing raw images directly to post-processing...")
            else:
                self.log("\n[2/4] ⚠️ Upscayl binary not found. Passing raw images directly to post-processing...")
            for img in kept_images:
                shutil.copy2(img, upscaled_folder / img.name)
        else:
            for group_type in ("isolated", "scene"):
                group_imgs = [p for p in kept_images if image_types.get(p.stem) == group_type]
                if not group_imgs:
                    continue

                model_name = self.upscaler.get_model_for_type(group_type)
                self.log(f"\n[2/4] AI Super-Resolution 4x [{group_type.upper()}] ({len(group_imgs)} images via {model_name})...")

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

        # 3. Post-Processing
        # Determine output folder: custom_output_folder > config.output_dir > folder / "result"
        if custom_output_folder:
            result_folder = custom_output_folder
        elif self.config.output_dir:
            result_folder = self.config.output_dir / folder.name
        else:
            result_folder = folder / "result"

        result_folder.mkdir(parents=True, exist_ok=True)
        if self.config.bg_output_dir:
            self.config.bg_output_dir.mkdir(parents=True, exist_ok=True)

        self.log(f"\n[3/4] High-Precision Post-Processing -> {result_folder}...")

        upscaled_files = sorted(list(upscaled_folder.glob("*.png")) + list(upscaled_folder.glob("*.jpg")) + list(upscaled_folder.glob("*.jpeg")))
        processed_items: List[tuple] = []

        for idx, up_file in enumerate(upscaled_files, start=1):
            if not self.config.remove_bg:
                img_type = "scene"
            else:
                img_type = image_types.get(up_file.stem, "isolated" if asset_type == "auto" else asset_type)

            out_ext = ".png" if img_type == "isolated" else ".jpg"
            clean_filename = sanitize_filename(up_file.stem, ext=out_ext, max_len=self.config.max_filename_chars)
            target_out = result_folder / clean_filename

            # Handle name collisions if multiple files sanitize to identical stems
            collision_idx = 1
            while target_out.exists() and target_out.name != f"{up_file.stem}{out_ext}":
                suffix = f"_{collision_idx}"
                stem_len = self.config.max_filename_chars - len(out_ext) - len(suffix)
                safe_stem = sanitize_filename(up_file.stem, ext="", max_len=stem_len).rstrip("_-")
                target_out = result_folder / f"{safe_stem}{suffix}{out_ext}"
                collision_idx += 1

            if img_type == "isolated":
                ok, err = self.postprocessor.process_isolated_png(up_file, target_out, log_callback=self.log)
                # If separate bg_output_dir is configured, also copy cutout there
                if ok and self.config.bg_output_dir:
                    shutil.copy2(target_out, self.config.bg_output_dir / target_out.name)
            else:
                ok, err = self.postprocessor.process_scene_jpeg(up_file, target_out, log_callback=self.log)

            if ok:
                processed_items.append((target_out, img_type))
                self.log(f"  • Processed [{idx}/{len(upscaled_files)}] ({img_type.upper()}): {target_out.name} ✅")
            else:
                self.log(f"  ❌ Post-processing failed on {up_file.name}: {err}")

        # 4. Technical Validation
        self.log(f"\n[4/4] Technical Validation...")
        passed_records: List[Dict[str, Any]] = []
        rejected_qa_folder = folder / "rejected_qa"

        for final_path, img_type in processed_items:
            val_res = self.validator.validate_asset(final_path, asset_type=img_type)
            if not val_res["is_valid"]:
                self.log(f"  ❌ Validation FAILED for {final_path.name}: {val_res['errors']}")
                rejected_qa_folder.mkdir(parents=True, exist_ok=True)
                shutil.move(final_path, rejected_qa_folder / final_path.name)
                continue

            self.log(f"  ✅ READY: {final_path.name} ({val_res['stats'].get('megapixels')} MP, {val_res['stats'].get('file_size_mb')} MB)")
            if val_res["warnings"]:
                for w in val_res["warnings"]:
                    self.log(f"     ⚠️ {w}")

            passed_records.append(val_res)

        self.log(f"\n🎉 Finished! {len(passed_records)} production-ready images saved to: {result_folder}")

        return {
            "folder": folder.name,
            "passed": len(passed_records),
            "failed": len(raw_images) - len(passed_records),
            "result_folder": result_folder
        }

    def print_submission_checklist(self):
        """Prints a high-visibility reminder of the Adobe Stock Contributor upload requirements."""
        self.log("\n==================================================")
        self.log("📋 ADOBE STOCK SUBMISSION CHECKLIST (MANDATORY)")
        self.log("==================================================")
        self.log("When uploading to https://contributor.stock.adobe.com/:")
        self.log(" 1. ☑️ Check: 'Created using generative AI tools' (MANDATORY for AI assets)")
        self.log(" 2. ☑️ Check: 'People and Property are fictional' (If depicting fictional subjects)")
        self.log(" 3. 🔍 Inspect at 100% zoom before clicking 'Submit for Review'.")
        self.log("==================================================\n")
