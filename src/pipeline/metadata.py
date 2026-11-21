"""
Adobe Stock Metadata Engine & CSV Exporter.
Fast, offline, deterministic metadata generation conforming to:
https://helpx.adobe.com/stock/contributor/help/csv-metadata.html
"""

import csv
from pathlib import Path
from typing import Dict, Any, List, Optional

from .config import PipelineConfig
from .categories import ADOBE_STOCK_CATEGORIES
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
        # Determine theme hint from prompt_hint or folder/filename
        theme = prompt_hint if prompt_hint else image_path.parent.name.replace("_result", "").replace("_upscaled", "")
        theme = theme.replace("_", " ")

        # 1. Infer Category ID (1 to 21)
        cat_id, cat_name = LocalMetadataEngine.infer_category(theme)

        # 2. Generate clean title (<= 70 chars, no commas)
        title = LocalMetadataEngine.generate_title(
            theme,
            asset_type=asset_type,
            max_chars=self.config.max_title_chars
        )

        # 3. Generate 30 to 45 high-relevance keywords
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
