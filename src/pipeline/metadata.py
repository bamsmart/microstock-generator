"""
Adobe Stock Metadata Engine, Optional ExifTool IPTC/XMP Embedder, & CSV Exporter.
Conforms to official Adobe Stock specification:
https://helpx.adobe.com/stock/contributor/help/csv-metadata.html
"""

import csv
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from .categories import ADOBE_STOCK_CATEGORIES
from .config import PipelineConfig
from .local_metadata import LocalMetadataEngine


class MetadataEngine:
    def __init__(self, config: PipelineConfig):
        self.config = config

    def generate_metadata_for_image(
        self,
        image_path: Path,
        prompt_hint: Optional[str] = None,
        asset_type: str = "isolated"
    ) -> Dict[str, Any]:
        """
        Generate commercial stock title, keywords, and category ID instantly (offline).
        Uses local semantic taxonomy and keyword expansions.
        """
        theme = prompt_hint if prompt_hint else image_path.parent.name.replace("_result", "").replace("_upscaled", "")
        theme = theme.replace("_", " ")

        cat_id, cat_name = LocalMetadataEngine.infer_category(theme)
        title = LocalMetadataEngine.generate_title(
            theme,
            asset_type=asset_type,
            max_chars=self.config.max_title_chars
        )
        keywords = LocalMetadataEngine.generate_keywords(
            theme,
            asset_type=asset_type,
            max_count=self.config.max_keywords
        )

        return {
            "title": title,
            "keywords": keywords,
            "category_id": cat_id,
            "category_name": cat_name
        }

    @staticmethod
    def has_exiftool() -> bool:
        return shutil.which("exiftool") is not None

    @staticmethod
    def embed_iptc_xmp_exiftool(
        file_path: Path,
        title: str,
        keywords: List[str],
        log_callback=None
    ) -> bool:
        """
        Embed Title and Keywords directly into JPEG/PNG IPTC & XMP metadata via ExifTool
        (if installed on system PATH). Gracefully skips if ExifTool is not installed.
        """
        exiftool_bin = shutil.which("exiftool")
        if not exiftool_bin:
            return False

        cmd = [
            exiftool_bin,
            "-overwrite_original",
            "-charset", "utf8",
            f"-IPTC:ObjectName={title}",
            f"-XMP:Title={title}",
            f"-IPTC:Caption-Abstract={title}",
            f"-XMP:Description={title}",
            "-IPTC:Keywords=",
            "-XMP:Subject=",
        ]
        for kw in keywords:
            k = kw.strip()
            if k:
                cmd.append(f"-IPTC:Keywords={k}")
                cmd.append(f"-XMP:Subject={k}")
        cmd.append(str(file_path))

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            if proc.returncode == 0:
                return True
            if log_callback:
                log_callback(f"  ⚠️ ExifTool warning on {file_path.name}: {proc.stderr.strip()}")
            return False
        except Exception as e:
            if log_callback:
                log_callback(f"  ⚠️ ExifTool error on {file_path.name}: {e}")
            return False

    @staticmethod
    def export_adobe_csv(records: List[Dict[str, Any]], csv_path: Path):
        """
        Write or update adobe_stock_metadata.csv.
        Adobe Stock official CSV format:
        Filename,Title,Keywords,Category,Releases
        """
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        file_exists = csv_path.exists()

        existing_rows: Dict[str, Dict[str, Any]] = {}
        if file_exists:
            try:
                with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
                    reader = csv.DictReader(f)
                    for r in reader:
                        fn = r.get("Filename")
                        if fn:
                            existing_rows[fn] = r
            except Exception:
                pass

        for rec in records:
            fn = rec["filename"]
            kw_str = ", ".join(rec.get("keywords", [])) if isinstance(rec.get("keywords"), list) else str(rec.get("keywords", ""))
            existing_rows[fn] = {
                "Filename": fn,
                "Title": rec.get("title", ""),
                "Keywords": kw_str,
                "Category": str(rec.get("category_id", 8)),
                "Releases": rec.get("releases", "")
            }

        fieldnames = ["Filename", "Title", "Keywords", "Category", "Releases"]
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in existing_rows.values():
                writer.writerow(row)
