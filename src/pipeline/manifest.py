"""
State tracking and manifest manager for processed assets.
Keeps records of processed hashes, filenames, prompts, and metadata.
"""

import json
import hashlib
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime


def calculate_file_hash(file_path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


class ManifestManager:
    def __init__(self, manifest_file: Path):
        self.manifest_file = manifest_file
        self.data: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        if self.manifest_file.exists():
            try:
                with open(self.manifest_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"records": {}, "created_at": datetime.now().isoformat()}

    def save(self):
        self.manifest_file.parent.mkdir(parents=True, exist_ok=True)
        self.data["updated_at"] = datetime.now().isoformat()
        temp_file = self.manifest_file.with_suffix(".tmp")
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
            temp_file.replace(self.manifest_file)
        except Exception:
            if temp_file.exists():
                temp_file.unlink(missing_ok=True)

    def is_processed(self, file_hash: str) -> bool:
        return file_hash in self.data.get("records", {})

    def record_asset(
        self,
        file_hash: str,
        original_name: str,
        output_name: str,
        asset_type: str,
        dimensions: tuple,
        megapixels: float,
        file_size_mb: float,
        prompt: Optional[str] = None,
        title: Optional[str] = None,
        keywords: Optional[list] = None,
        category_id: Optional[int] = None
    ):
        self.data.setdefault("records", {})[file_hash] = {
            "original_name": original_name,
            "output_name": output_name,
            "asset_type": asset_type,
            "dimensions": f"{dimensions[0]}x{dimensions[1]}",
            "megapixels": round(megapixels, 2),
            "file_size_mb": round(file_size_mb, 2),
            "prompt": prompt or "",
            "title": title or "",
            "keywords": keywords or [],
            "category_id": category_id or 8,
            "timestamp": datetime.now().isoformat()
        }
        self.save()

