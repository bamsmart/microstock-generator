"""
Commercial Microstock Technical Validator & Scientific Image Quality Inspector.
Enforces all rules required for commercial stock asset approval:
- Resolution: 4 MP <= Megapixels <= 100 MP
- File size: <= 45.0 MB
- Filename length: <= 30 characters
- Color profile: sRGB / RGBA transparency check
- Scientific Quality: Resolution-invariant blur (skimage.measure.blur_effect),
  Wavelet noise (skimage.restoration.estimate_sigma), Cutout Halo Rim Detector,
  Histogram clipping & Laplacian variance
"""

from pathlib import Path
from typing import Dict, Any, Optional
import numpy as np
from PIL import Image
import cv2

try:
    from skimage.measure import blur_effect as skimage_blur_effect
    from skimage.restoration import estimate_sigma as skimage_estimate_sigma
except ImportError:
    skimage_blur_effect = None
    skimage_estimate_sigma = None

from .config import PipelineConfig

Image.MAX_IMAGE_PIXELS = 250_000_000


def detect_isolated_halo_score(rgba_arr: np.ndarray) -> float:
    """
    Inspect the 1-3px semi-transparent boundary of an RGBA cutout against
    adjacent interior core pixels. Returns 0.0 (zero halo) to 1.0 (heavy white matte rim).
    """
    if rgba_arr.ndim != 3 or rgba_arr.shape[2] < 4:
        return 0.0
    rgb = rgba_arr[:, :, :3].astype(np.float32)
    alpha = rgba_arr[:, :, 3]

    fringe = (alpha > 10) & (alpha < 245)
    if np.count_nonzero(fringe) < 25:
        return 0.0

    ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    core = cv2.erode((alpha >= 245).astype(np.uint8), ker) > 0
    if np.count_nonzero(core) < 50:
        return 0.0

    inv_core = (~core).astype(np.uint8)
    _, labels = cv2.distanceTransformWithLabels(inv_core, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
    zero_coords = np.argwhere(inv_core == 0)
    nearest_yx = zero_coords[labels[fringe] - 1]
    core_rgb = rgb[nearest_yx[:, 0], nearest_yx[:, 1]]
    fringe_rgb = rgb[fringe]

    # Rec. 601 luminance comparison; ignore naturally white/light-gray objects (core_luma >= 210)
    core_luma = 0.299 * core_rgb[:, 0] + 0.587 * core_rgb[:, 1] + 0.114 * core_rgb[:, 2]
    colored_mask = core_luma < 210.0
    if np.count_nonzero(colored_mask) < 15:
        return 0.0

    fringe_luma = 0.299 * fringe_rgb[:, 0] + 0.587 * fringe_rgb[:, 1] + 0.114 * fringe_rgb[:, 2]
    excess_bright = np.maximum(0.0, fringe_luma[colored_mask] - core_luma[colored_mask]) / 255.0
    return round(float(np.clip(np.mean(excess_bright) * 2.2, 0.0, 1.0)), 3)


def compute_scientific_iqa(rgb_sample: np.ndarray, gray_sample: np.ndarray) -> Dict[str, Optional[float]]:
    """
    Compute scale-invariant blur (skimage.measure.blur_effect, 0..1 lower=sharper)
    and wavelet noise sigma (skimage.restoration.estimate_sigma).
    """
    out: Dict[str, Optional[float]] = {"blur_effect": None, "noise_sigma": None}
    if rgb_sample.size == 0 or gray_sample.size == 0:
        return out

    # Cap analysis grid to <= 1536px longest side so latency is < 0.15s per image
    h, w = gray_sample.shape[:2]
    max_dim = max(h, w)
    if max_dim > 1536:
        scale = 1536.0 / float(max_dim)
        nw, nh = max(64, int(round(w * scale))), max(64, int(round(h * scale)))
        gray_work = cv2.resize(gray_sample, (nw, nh), interpolation=cv2.INTER_AREA)
        rgb_work = cv2.resize(rgb_sample, (nw, nh), interpolation=cv2.INTER_AREA)
    else:
        gray_work = gray_sample
        rgb_work = rgb_sample

    if skimage_blur_effect is not None and min(gray_work.shape[:2]) >= 16:
        try:
            blur_val = float(skimage_blur_effect(gray_work, h_size=11))
            if np.isfinite(blur_val):
                out["blur_effect"] = round(blur_val, 3)
        except Exception:
            pass

    if skimage_estimate_sigma is not None and min(rgb_work.shape[:2]) >= 16:
        try:
            sigma_val = float(skimage_estimate_sigma(rgb_work, channel_axis=-1, average_sigmas=True))
            if np.isfinite(sigma_val):
                out["noise_sigma"] = round(sigma_val, 2)
        except Exception:
            pass

    return out


class TechnicalValidator:
    def __init__(self, config: PipelineConfig):
        self.config = config

    def validate_asset(self, file_path: Path, asset_type: str = "isolated") -> Dict[str, Any]:
        """
        Validate single output file against Adobe Stock guidelines.
        Returns a dict with: is_valid (bool), errors (list), warnings (list), stats (dict).
        """
        results: Dict[str, Any] = {
            "path": str(file_path),
            "filename": file_path.name,
            "asset_type": asset_type,
            "is_valid": True,
            "errors": [],
            "warnings": [],
            "stats": {}
        }

        # 0. Check existence (file may have been manually deleted during processing)
        if not file_path.exists():
            results["errors"].append("File not found (removed or moved during processing).")
            results["is_valid"] = False
            results["missing"] = True
            return results

        # 1. Filename length check (<= 30 characters for Adobe Stock CSV)
        if len(file_path.name) > self.config.max_filename_chars:
            results["errors"].append(
                f"Filename length is {len(file_path.name)} chars (exceeds Adobe limit of {self.config.max_filename_chars} chars)."
            )

        # 2. File size check (<= 45 MB)
        file_size_mb = file_path.stat().st_size / (1024 * 1024)
        results["stats"]["file_size_mb"] = round(file_size_mb, 2)
        if file_size_mb > self.config.max_file_size_mb:
            results["errors"].append(
                f"File size {file_size_mb:.2f} MB exceeds maximum allowed limit of {self.config.max_file_size_mb} MB."
            )

        try:
            with Image.open(file_path) as img:
                w, h = img.size
                mp = (w * h) / 1_000_000.0
                results["stats"]["width"] = w
                results["stats"]["height"] = h
                results["stats"]["megapixels"] = round(mp, 2)
                results["stats"]["mode"] = img.mode
                results["stats"]["format"] = img.format

                # 3. Resolution check (4 MP <= MP <= 100 MP)
                if mp < self.config.min_megapixels:
                    results["errors"].append(
                        f"Resolution is {mp:.2f} MP (minimum required is {self.config.min_megapixels} MP)."
                    )
                elif mp > self.config.max_megapixels:
                    results["errors"].append(
                        f"Resolution is {mp:.2f} MP (maximum allowed is {self.config.max_megapixels} MP)."
                    )

                # 4. Format & Mode check
                if asset_type == "isolated":
                    if img.format != "PNG":
                        results["errors"].append(f"Isolated asset must be PNG, found {img.format}.")
                    if img.mode != "RGBA":
                        results["errors"].append(f"Isolated asset must be RGBA (transparency), found {img.mode}.")
                    else:
                        alpha = np.array(img.split()[3])
                        transparent_ratio = np.count_nonzero(alpha < 10) / alpha.size
                        solid_ratio = np.count_nonzero(alpha > 240) / alpha.size
                        results["stats"]["transparency_ratio"] = round(transparent_ratio, 3)

                        if transparent_ratio < 0.05:
                            results["warnings"].append("Very low transparency ratio (<5%). Ensure background was cleanly removed.")
                        if solid_ratio < 0.05:
                            results["errors"].append("Subject is almost entirely transparent or empty.")

                elif asset_type == "scene":
                    if img.format not in ("JPEG", "JPG"):
                        results["errors"].append(f"Full-scene asset must be JPEG, found {img.format}.")
                    if img.mode != "RGB":
                        results["errors"].append(f"Scene asset must be RGB, found {img.mode}.")

                # 5. Local Quality: Exposure (Histogram Clipping) & Sharpness
                np_img = np.array(img)
                if img.mode == "RGBA":
                    mask = np_img[:, :, 3] > 20
                    rgb_pixels = np_img[:, :, :3][mask]
                else:
                    rgb_pixels = np_img.reshape(-1, 3)

                if rgb_pixels.size > 0:
                    # Blown highlights (>252 in R,G,B)
                    blown = np.all(rgb_pixels > 252, axis=-1)
                    blown_pct = (np.count_nonzero(blown) / len(rgb_pixels)) * 100
                    # Crushed shadows (<4 in R,G,B)
                    crushed = np.all(rgb_pixels < 4, axis=-1)
                    crushed_pct = (np.count_nonzero(crushed) / len(rgb_pixels)) * 100

                    results["stats"]["blown_highlights_pct"] = round(blown_pct, 1)
                    results["stats"]["crushed_shadows_pct"] = round(crushed_pct, 1)

                    if blown_pct > 35.0:
                        results["warnings"].append(f"High percentage of clipped/blown highlights ({blown_pct:.1f}%).")
                    if crushed_pct > 35.0:
                        results["warnings"].append(f"High percentage of crushed shadows ({crushed_pct:.1f}%).")

                # Sharpness check via cv2 Laplacian variance + Scientific IQA (skimage) + Halo Detector
                if img.mode in ("RGB", "RGBA"):
                    rgb_arr = np_img[:, :, :3]
                    gray = cv2.cvtColor(rgb_arr, cv2.COLOR_RGB2GRAY)
                    laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
                    results["stats"]["sharpness_score"] = round(laplacian_var, 1)
                    if laplacian_var < 20.0:
                        results["warnings"].append(f"Image may be too blurry (Sharpness: {laplacian_var:.1f}).")

                    iqa = compute_scientific_iqa(rgb_arr, gray)
                    if iqa["blur_effect"] is not None:
                        results["stats"]["blur_effect"] = iqa["blur_effect"]
                        max_blur = float(getattr(self.config, "max_blur_effect", 0.45))
                        if iqa["blur_effect"] > max_blur:
                            results["warnings"].append(
                                f"Elevated perceptual blur (blur_effect={iqa['blur_effect']:.2f} > {max_blur:.2f})."
                            )
                    if iqa["noise_sigma"] is not None:
                        results["stats"]["noise_sigma"] = iqa["noise_sigma"]
                        max_sigma = float(getattr(self.config, "max_noise_sigma", 12.0))
                        if iqa["noise_sigma"] > max_sigma:
                            results["warnings"].append(
                                f"Elevated color/grain noise (noise_sigma={iqa['noise_sigma']:.1f} > {max_sigma:.1f})."
                            )

                if asset_type == "isolated" and img.mode == "RGBA":
                    halo_score = detect_isolated_halo_score(np_img)
                    results["stats"]["halo_score"] = halo_score
                    max_halo = float(getattr(self.config, "max_halo_score", 0.28))
                    if halo_score > max_halo:
                        results["warnings"].append(
                            f"Possible white edge halo detected on cutout boundary (halo_score={halo_score:.2f} > {max_halo:.2f})."
                        )

        except Exception as e:
            results["errors"].append(f"Failed to read image file: {e}")

        results["is_valid"] = len(results["errors"]) == 0
        return results

