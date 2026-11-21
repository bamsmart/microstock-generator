"""
Perceptual Hashing and Deduplication Module.
Prevents "Similar Content" rejections by Adobe Stock reviewers.
"""

from pathlib import Path
from typing import List, Tuple, Set
from PIL import Image, ImageOps

try:
    import imagehash
except ImportError:
    imagehash = None


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

