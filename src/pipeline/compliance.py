"""
Commercial Microstock Compliance & Linter Engine.
Strictly checks and sanitizes titles, keywords, and filenames according to microstock guidelines.
"""

import re
from pathlib import Path
from typing import List, Tuple, Dict, Any

# Prohibited keywords, artist names, brands, and spam phrases
FORBIDDEN_KEYWORDS = {
    # AI buzzwords prohibited in Title/Keywords
    "generative ai", "generativeai", "ai generated", "ai-generated", "artificial intelligence",
    "dall-e", "dalle", "midjourney", "stable diffusion", "firefly", "gemini", "imagen",
    "prompt", "photorealistic", "hyperrealistic", "unreal engine", "octane render", "trending", "4k", "8k", "hd",

    # Major Brands & Trademarks (strict non-compliance rejection)
    "apple", "iphone", "ipad", "macbook", "samsung", "galaxy", "google", "android",
    "nike", "adidas", "puma", "gucci", "prada", "louis vuitton", "chanel", "hermes",
    "coca-cola", "cocacola", "coke", "pepsi", "starbucks", "mcdonalds", "disney", "marvel",
    "lego", "barbie", "sony", "playstation", "xbox", "nintendo", "tesla", "bmw", "mercedes",

    # Real living or deceased artists (strictly prohibited by Adobe Stock AI policies)
    "picasso", "van gogh", "monet", "da vinci", "rembrandt", "warhol", "banksy",
    "greg rutkowski", "artgerm", "alphonse mucha", "beeple", "makoto shinkai"
}


def sanitize_filename(base_name: str, ext: str = ".png", max_len: int = 30) -> str:
    """
    Sanitize filename to be strictly <= max_len characters (including extension).
    Only allows lowercase alphanumeric characters and hyphens/underscores.
    """
    ext = ext.lower()
    if not ext.startswith("."):
        ext = f".{ext}"

    # Clean base name
    clean = re.sub(r"[^a-zA-Z0-9_\-]", "_", base_name).strip("_-").lower()
    clean = re.sub(r"_{2,}", "_", clean)

    allowed_base_len = max_len - len(ext)
    if len(clean) > allowed_base_len:
        clean = clean[:allowed_base_len].rstrip("_-")

    if not clean:
        clean = "asset"

    return f"{clean}{ext}"


def lint_title(title: str, max_chars: int = 70) -> Tuple[str, List[str]]:
    """
    Lint title for Adobe Stock:
    - Max 70 characters
    - Avoid commas or special symbols
    - Omit prohibited terms (e.g. 'generative AI')
    """
    warnings: List[str] = []
    cleaned = title.strip()

    # Remove commas (Adobe Stock recommends plain phrase)
    if "," in cleaned:
        cleaned = cleaned.replace(",", " ")
        warnings.append("Commas removed from title.")

    # Remove extra spaces
    cleaned = re.sub(r"\s+", " ", cleaned)

    # Check forbidden terms
    lower_t = cleaned.lower()
    for forbidden in FORBIDDEN_KEYWORDS:
        if forbidden in lower_t:
            pattern = re.compile(re.escape(forbidden), re.IGNORECASE)
            cleaned = pattern.sub("", cleaned)
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            warnings.append(f"Removed prohibited term '{forbidden}' from title.")

    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars].rstrip()
        warnings.append(f"Title truncated to {max_chars} chars.")

    return cleaned, warnings


def lint_keywords(keywords: List[str], max_count: int = 50) -> Tuple[List[str], List[str]]:
    """
    Lint keywords for Adobe Stock:
    - Up to 50 keywords max
    - Remove duplicates while preserving relevance order
    - Remove forbidden terms and buzzword spam
    """
    warnings: List[str] = []
    seen = set()
    cleaned_list: List[str] = []

    for kw in keywords:
        k = kw.strip().lower()
        if not k:
            continue
        # Check against forbidden words
        is_forbidden = False
        for forbidden in FORBIDDEN_KEYWORDS:
            if forbidden == k or f" {forbidden} " in f" {k} ":
                is_forbidden = True
                warnings.append(f"Dropped forbidden keyword: '{kw}'")
                break

        if not is_forbidden and k not in seen:
            seen.add(k)
            cleaned_list.append(k)

    if len(cleaned_list) > max_count:
        cleaned_list = cleaned_list[:max_count]
        warnings.append(f"Keywords list capped at {max_count}.")

    return cleaned_list, warnings

