"""
Commercial Microstock Compliance & Linter Engine.
Strictly checks and sanitizes titles, keywords, and filenames according to microstock guidelines.
"""

import re
from typing import List, Tuple

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

# Protected landmarks / recognizable architecture that trigger Adobe Stock IP rejections
PROTECTED_LANDMARKS = {
    "eiffel tower", "statue of liberty", "taj mahal", "colosseum", "burj khalifa",
    "hollywood sign", "hollywood", "louvre", "sydney opera house", "empire state building",
    "golden gate bridge", "big ben", "disneyland", "chrysler building", "space needle"
}

# Prompt spam buzzwords that cause over-processed "AI plastic" technical rejections
AI_PROMPT_BUZZWORDS = {
    "masterpiece", "award winning", "award-winning", "ultra detailed", "ultra-detailed",
    "hyperdetailed", "trending on artstation", "artstation", "cgsociety", "8k resolution",
    "4k resolution", "photorealistic", "hyperrealistic", "unreal engine", "octane render",
    "vray", "best quality", "insanely detailed", "hdr"
}

# Weak/generic filler words that dilute Adobe Stock SEO ranking
GENERIC_FILLER_KEYWORDS = {
    "beautiful", "nice", "good", "cool", "amazing", "awesome", "pretty", "best",
    "high quality", "high resolution", "image", "picture", "visual", "thing",
    "stuff", "item", "object", "element", "creative", "artistic", "style",
    "decorative", "concept", "design", "art", "layout", "backdrop"
}


def sanitize_filename(base_name: str, ext: str = ".png", max_len: int = 30) -> str:
    """
    Sanitize filename to be strictly <= max_len characters (including extension).
    Only allows lowercase alphanumeric characters and hyphens/underscores.
    """
    if ext:
        ext = ext.lower()
        if not ext.startswith("."):
            ext = f".{ext}"
    else:
        ext = ""

    # Clean base name
    clean = re.sub(r"[^a-zA-Z0-9_\-]", "_", base_name).strip("_-").lower()
    clean = re.sub(r"_{2,}", "_", clean)

    allowed_base_len = max(1, max_len - len(ext))
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


def lint_commercial_prompt(prompt: str, asset_type: str = "scene") -> Tuple[str, List[str]]:
    """
    Enforce Adobe Stock Commercial-Grade Generative AI Rules on image generation prompts:
    1. Strips forbidden brands, artists, 'in the style of ...', protected landmarks, and AI plastic buzzwords.
    2. Guarantees mandatory commercial guardrails (no text/logos/watermarks, copy space for scenes,
       pure solid #FFFFFF white background + full uncropped silhouette + no drop shadows for isolated).
    Returns: (compliant_prompt, warnings)
    """
    warnings: List[str] = []
    cleaned = prompt.strip()

    # 1. Remove "in the style of <artist/reference>" phrases (strict Adobe Stock GenAI violation)
    style_pattern = re.compile(r",?\s*\bin the style of\s+[^,.;]+", re.IGNORECASE)
    if style_pattern.search(cleaned):
        cleaned = style_pattern.sub("", cleaned)
        warnings.append("Removed prohibited 'in the style of ...' reference.")

    # 2. Strip forbidden brands/artists, protected landmarks, and AI plastic buzzwords
    all_banned = FORBIDDEN_KEYWORDS | PROTECTED_LANDMARKS | AI_PROMPT_BUZZWORDS
    for term in sorted(all_banned, key=len, reverse=True):
        pattern = re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)
        if pattern.search(cleaned):
            cleaned = pattern.sub("", cleaned)
            warnings.append(f"Removed non-compliant term '{term}' from prompt.")

    # Clean punctuation artifacts left after stripping
    cleaned = re.sub(r"\s*,\s*,+", ", ", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).replace(" ,", ",").strip(" ,.")

    lower = cleaned.lower()

    # 3. Guarantee mandatory commercial guardrails per asset type
    additions: List[str] = []
    if asset_type == "isolated":
        if "white background" not in lower and "#ffffff" not in lower:
            additions.append("isolated on a pure solid white background (#FFFFFF)")
        if "uncropped" not in lower and "margin" not in lower and "filling" not in lower:
            additions.append("centered full uncropped silhouette filling 78% of frame with clean margin")
        if "no drop shadow" not in lower and "no cast shadow" not in lower and "no ground shadow" not in lower:
            additions.append("soft even studio lighting, crisp edges, no drop shadows")
    else:
        if "copy space" not in lower and "negative space" not in lower:
            additions.append("generous clean negative copy space for designer typography")
        if "texture" not in lower and "authentic" not in lower and "natural" not in lower:
            additions.append("authentic natural textures, realistic editorial color grading")

    if "no text" not in lower:
        additions.append("no text")
    if "no logo" not in lower:
        additions.append("no logos")
    if "no watermark" not in lower:
        additions.append("no watermarks")

    if additions:
        cleaned = f"{cleaned}, {', '.join(additions)}"

    return cleaned, warnings

