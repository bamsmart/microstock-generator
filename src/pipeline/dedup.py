"""
Perceptual Hashing, Raw Integrity Preflight, & Cross-Batch Portfolio Index.
Prevents corrupted input crashes and Adobe Stock "Similar Content" rejections.
"""

from datetime import datetime
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from PIL import Image, ImageOps

try:
    import imagehash
except ImportError:
    imagehash = None

Image.MAX_IMAGE_PIXELS = 250_000_000


def validate_raw_image_readable(img_path: Path) -> Tuple[bool, str]:
    """
    Preflight corrupt-image check before Stage 1/2/3.
    Catches 0-byte downloads, truncated headers, and invalid image streams cleanly.
    """
    try:
        if not img_path.exists():
            return False, "File missing"
        if img_path.stat().st_size <= 0:
            return False, "0-byte file"
        with Image.open(img_path) as im:
            im.verify()
        with Image.open(img_path) as im2:
            w, h = im2.size
            if w <= 0 or h <= 0:
                return False, f"Invalid dimensions {w}x{h}"
        return True, "OK"
    except Exception as e:
        return False, f"Unreadable/corrupt image: {e}"


class PortfolioIndex:
    """
    Cross-batch persistent portfolio index (.portfolio_index.json) storing
    pHash, keyword sets, and optional CLIP embeddings to protect against
    Adobe Stock "Similar Content" rejections across daily/monthly batches.
    """

    def __init__(self, index_path: Path):
        self.path = index_path
        self.entries: List[Dict[str, Any]] = self._load()

    def _load(self) -> List[Dict[str, Any]]:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                entries = data.get("entries", [])
                return entries if isinstance(entries, list) else []
            except Exception:
                return []
        return []

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        try:
            tmp.write_text(
                json.dumps({"entries": self.entries}, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            tmp.replace(self.path)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink(missing_ok=True)
                except Exception:
                    pass

    def find_similar_phash(
        self,
        phash: str,
        threshold: int = 6,
        exclude_filename: Optional[str] = None,
    ) -> Optional[Tuple[Dict[str, Any], int]]:
        if not phash:
            return None
        best_match: Optional[Tuple[Dict[str, Any], int]] = None
        for entry in self.entries:
            fn = entry.get("filename")
            if exclude_filename and fn == exclude_filename:
                continue
            eh = entry.get("phash", "")
            if not eh:
                continue
            dist = hamming_distance(phash, eh)
            if dist <= threshold:
                if best_match is None or dist < best_match[1]:
                    best_match = (entry, dist)
        return best_match

    def find_keyword_overlap(
        self,
        keywords: List[str],
        threshold: float = 0.65,
        exclude_filename: Optional[str] = None,
    ) -> Optional[Tuple[Dict[str, Any], float]]:
        kw_set = {k.strip().lower() for k in keywords if k and k.strip()}
        if not kw_set:
            return None
        best: Optional[Tuple[Dict[str, Any], float]] = None
        for entry in self.entries:
            fn = entry.get("filename")
            if exclude_filename and fn == exclude_filename:
                continue
            other_kws = {k.strip().lower() for k in entry.get("keywords", []) if k and k.strip()}
            if not other_kws:
                continue
            union = kw_set | other_kws
            if not union:
                continue
            overlap = len(kw_set & other_kws) / float(len(union))
            if overlap >= threshold:
                if best is None or overlap > best[1]:
                    best = (entry, round(overlap, 3))
        return best

    def record_asset(
        self,
        filename: str,
        batch: str,
        phash: str = "",
        keywords: Optional[List[str]] = None,
        clip_vec: Optional[List[float]] = None,
    ):
        updated = {
            "filename": filename,
            "batch": batch,
            "phash": phash,
            "keywords": list(keywords or []),
            "clip_vec": list(clip_vec) if clip_vec is not None else None,
            "date": datetime.now().isoformat(timespec="seconds"),
        }
        for i, entry in enumerate(self.entries):
            if entry.get("filename") == filename and entry.get("batch") == batch:
                # Preserve existing clip_vec / phash if omitted on update
                if not updated["phash"] and entry.get("phash"):
                    updated["phash"] = entry["phash"]
                if updated["clip_vec"] is None and entry.get("clip_vec") is not None:
                    updated["clip_vec"] = entry["clip_vec"]
                self.entries[i] = updated
                return
        self.entries.append(updated)


def compute_phash(img_path: Path) -> str:
    """Compute perceptual hash for an image."""
    with Image.open(img_path) as raw_img:
        img = ImageOps.exif_transpose(raw_img)
        img_rgb = img.convert("RGB")
        if imagehash is not None:
            return str(imagehash.phash(img_rgb))
        else:
            # Fallback 64-bit difference hash (dHash) using pure PIL
            resized = img_rgb.resize((9, 8), Image.Resampling.LANCZOS).convert("L")
            pixels = list(resized.getdata())
            diff = []
            for row in range(8):
                for col in range(8):
                    pixel_left = pixels[row * 9 + col]
                    pixel_right = pixels[row * 9 + col + 1]
                    diff.append(pixel_left > pixel_right)
            decimal_value = 0
            hex_string = []
            for index, value in enumerate(diff):
                if value:
                    decimal_value += 2 ** (index % 8)
                if (index % 8) == 7:
                    hex_string.append(hex(decimal_value)[2:].rjust(2, "0"))
                    decimal_value = 0
            return "".join(hex_string)


def hamming_distance(hash1: str, hash2: str) -> int:
    """Compute Hamming distance between two hexadecimal hash strings."""
    try:
        val1 = int(hash1, 16)
        val2 = int(hash2, 16)
        xor_val = val1 ^ val2
        return bin(xor_val).count("1")
    except Exception:
        return 999


def filter_near_duplicates(
    image_paths: List[Path],
    threshold: int = 6
) -> Tuple[List[Path], List[Tuple[Path, Path, int]]]:
    """
    Filter out images that are perceptually too similar.
    Threshold: <= 6 is considered very similar / duplicate.
    Returns: (kept_images, rejected_pairs_with_distance)
    """
    kept: List[Path] = []
    kept_hashes: List[Tuple[Path, str]] = []
    rejected: List[Tuple[Path, Path, int]] = []

    for img_path in sorted(image_paths):
        try:
            h = compute_phash(img_path)
            is_dup = False
            for prev_path, prev_h in kept_hashes:
                dist = hamming_distance(h, prev_h)
                if dist <= threshold:
                    rejected.append((img_path, prev_path, dist))
                    is_dup = True
                    break
            if not is_dup:
                kept.append(img_path)
                kept_hashes.append((img_path, h))
        except Exception:
            # If hashing fails, keep the image rather than dropping silently
            kept.append(img_path)

    return kept, rejected

