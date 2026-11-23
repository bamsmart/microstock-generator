"""
Commercial Microstock Technical Validator & Quality Inspector.
Enforces all rules required for commercial stock asset approval:
- Resolution: 4 MP <= Megapixels <= 100 MP
- File size: <= 45.0 MB
- Filename length: <= 30 characters
- Color profile: sRGB / RGBA transparency check
- Local Quality: Histogram clipping & sharpness validation
"""

from pathlib import Path
from typing import Dict, Any
import numpy as np
from PIL import Image
import cv2

from .config import PipelineConfig


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

                # Sharpness check via cv2 Laplacian variance
                if img.mode in ("RGB", "RGBA"):
                    gray = cv2.cvtColor(np_img[:, :, :3], cv2.COLOR_RGB2GRAY)
                    laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
                    results["stats"]["sharpness_score"] = round(laplacian_var, 1)
                    if laplacian_var < 20.0:
                        results["warnings"].append(f"Image may be too blurry (Sharpness: {laplacian_var:.1f}).")

        except Exception as e:
            results["errors"].append(f"Failed to read image file: {e}")

        results["is_valid"] = len(results["errors"]) == 0
        return results

