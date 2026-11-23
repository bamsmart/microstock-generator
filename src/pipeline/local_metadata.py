"""
Offline / Local SEO Taxonomy & Keyword Expander for Adobe Stock.
Generates commercial titles, 30-45 high-relevance keywords, and official Adobe Stock category IDs (1-21)
without calling any external API. Fast, deterministic, and 100% offline.
"""

import re
from typing import List, Tuple
from .categories import normalize_category_id, ADOBE_STOCK_CATEGORIES
from .compliance import lint_title, lint_keywords, FORBIDDEN_KEYWORDS

# Category keyword association mapping for automatic category detection (1-21)
CATEGORY_KEYWORDS = {
    1: {"animal", "animals", "cat", "dog", "puppy", "kitten", "bird", "lion", "tiger", "bear", "wildlife", "pet", "pets", "panda", "horse", "fish"},
    2: {"building", "architecture", "house", "home", "interior", "exterior", "room", "kitchen", "bedroom", "living room", "office", "apartment", "facade", "modern", "skyscraper"},
    3: {"business", "finance", "money", "office", "corporate", "meeting", "work", "worker", "strategy", "marketing", "success", "investment"},
    4: {"drink", "drinks", "beverage", "coffee", "tea", "cocktail", "juice", "wine", "beer", "cup", "mug", "glass", "barista"},
    5: {"environment", "nature", "forest", "tree", "trees", "mountain", "ocean", "sea", "climate", "ecology", "earth", "conservation"},
    6: {"emotion", "feeling", "happy", "sad", "love", "peace", "mood", "mind", "concept", "abstract", "dream", "fantasy"},
    7: {"food", "dessert", "fruit", "cake", "bakery", "bread", "meal", "dinner", "breakfast", "cooking", "snack", "tasty", "delicious"},
    8: {"graphic", "resource", "vector", "icon", "sticker", "symbol", "pattern", "texture", "template", "banner", "badge", "clipart", "isolated"},
    9: {"hobby", "leisure", "craft", "gaming", "game", "reading", "book", "music", "guitar", "paint", "drawing", "diy", "relaxation"},
    10: {"industry", "factory", "construction", "manufacturing", "engineering", "machine", "tools", "industrial", "warehouse"},
    11: {"landscape", "scenery", "sunset", "sunrise", "sky", "clouds", "valley", "lake", "river", "beach", "coast", "horizon"},
    12: {"lifestyle", "wellness", "fitness", "yoga", "healthy", "daily", "routine", "fashion", "style", "beauty", "cosmetics"},
    13: {"people", "person", "man", "woman", "child", "children", "baby", "family", "portrait", "face", "smile", "crowd"},
    14: {"plant", "flower", "flowers", "botanical", "leaf", "leaves", "rose", "floral", "garden", "succulent", "flora", "bloom"},
    15: {"culture", "religion", "spiritual", "tradition", "traditional", "festival", "temple", "church", "celebration", "folklore"},
    16: {"science", "medicine", "medical", "doctor", "health", "hospital", "laboratory", "research", "dna", "chemistry", "biology"},
    17: {"social", "community", "charity", "society", "diversity", "equality", "volunteer", "protest", "global"},
    18: {"sport", "sports", "football", "soccer", "basketball", "running", "gym", "athlete", "exercise", "workout", "fitness"},
    19: {"technology", "computer", "ai", "digital", "data", "cyber", "internet", "network", "software", "robot", "futuristic"},
    20: {"transport", "transportation", "car", "vehicle", "automobile", "airplane", "flight", "train", "ship", "boat", "traffic"},
    21: {"travel", "tourism", "vacation", "trip", "holiday", "destination", "landmark", "journey", "explore", "tourist"}
}

# Thematic keyword expansions for commercial stock indexing
THEMATIC_EXPANSIONS = {
    "christmas": ["christmas", "xmas", "holiday", "winter", "celebration", "december", "festive", "greeting", "decoration", "ornament", "traditional", "noel", "new year", "season", "gift"],
    "winter": ["winter", "cold", "snow", "snowy", "frost", "seasonal", "ice", "december", "january", "cozy", "weather"],
    "watercolor": ["watercolor", "watercolour", "hand drawn", "painted", "artistic", "illustration", "painting", "brush stroke", "creative", "textured"],
    "cat": ["cat", "kitten", "kitty", "feline", "cute", "pet", "domestic animal", "whiskers", "adorable", "furry", "companion"],
    "dog": ["dog", "puppy", "canine", "cute", "pet", "domestic animal", "adorable", "friendly", "furry", "companion"],
    "coffee": ["coffee", "cafe", "espresso", "cappuccino", "latte", "caffeine", "beverage", "aroma", "morning", "barista", "hot drink", "roast"],
    "flower": ["flower", "floral", "bloom", "blossom", "botanical", "petals", "nature", "summer", "spring", "garden", "natural", "flora"],
    "kitchen": ["kitchen", "interior", "home", "modern", "cooking", "countertop", "design", "furniture", "clean", "appliance", "room"],
    "living_room": ["living room", "interior", "home", "house", "modern", "cozy", "furniture", "sofa", "couch", "decor", "relaxing"],
    "sticker": ["sticker", "badge", "clipart", "emblem", "patch", "cutout", "isolated", "graphic", "die cut", "design element"],
    "vintage": ["vintage", "retro", "classic", "antique", "nostalgia", "aged", "rustic", "old fashioned", "heritage", "traditional"],
    "modern": ["modern", "contemporary", "minimalist", "sleek", "stylish", "clean", "trendy", "elegant", "design"],
    "nature": ["nature", "outdoors", "natural", "organic", "scenic", "environment", "peaceful", "fresh", "earth"],
    "food": ["food", "delicious", "tasty", "gourmet", "fresh", "cooking", "snack", "appetizing", "culinary", "ingredient"],
    "podium": ["podium", "pedestal", "product display", "cosmetic backdrop", "stage", "plinth", "travertine", "minimalist", "studio", "mockup", "e-commerce", "skincare", "packaging", "beige", "shadow"],
    "workspace": ["workspace", "desk", "home office", "remote work", "laptop", "productivity", "minimalist", "flatlay", "copy space", "interior", "business", "startup", "morning light", "oak"],
    "ramadan": ["ramadan", "eid", "islamic", "lantern", "crescent", "festive", "arabesque", "geometric", "gold", "hospitality", "dates", "celebration", "greeting", "middle east", "muslim"],
    "matcha": ["matcha", "green tea", "iced latte", "beverage", "cafe", "ceremonial", "oat milk", "drink", "refreshing", "glass", "ice cubes", "menu", "barista", "healthy"],
    "fintech": ["fintech", "finance", "security", "shield", "banking", "digital payment", "cybersecurity", "isometric", "3d icon", "trust", "investment", "saas", "app", "corporate"],
    "esg": ["sustainability", "esg", "renewable energy", "solar panel", "green energy", "wind turbine", "eco friendly", "climate", "clean tech", "environment", "carbon neutral", "future", "nature"],
    "spa": ["spa", "wellness", "aromatherapy", "essential oil", "eucalyptus", "relaxation", "skincare", "organic", "botanical", "self care", "zen", "linen", "calm", "natural"],
    "abstract": ["abstract", "glassmorphism", "translucent", "gradient", "wave", "ribbon", "futuristic", "technology", "corporate", "hero banner", "presentation", "minimalist", "clean", "backdrop"],
}


class LocalMetadataEngine:
    """Fast, deterministic, offline metadata generator for Adobe Stock."""

    @staticmethod
    def infer_category(text: str, default_id: int = 8) -> Tuple[int, str]:
        """Detect the best Adobe Stock Category (1-21) based on word frequency."""
        words = set(re.findall(r"\b[a-zA-Z]{3,}\b", text.lower()))
        best_id = default_id
        max_matches = 0

        for cat_id, cat_keywords in CATEGORY_KEYWORDS.items():
            matches = len(words.intersection(cat_keywords))
            if matches > max_matches:
                max_matches = matches
                best_id = cat_id

        cat_id = normalize_category_id(best_id)
        return cat_id, ADOBE_STOCK_CATEGORIES[cat_id]

    @staticmethod
    def generate_title(theme_hint: str, asset_type: str = "isolated", max_chars: int = 70) -> str:
        """
        Generate a concise, clean, descriptive stock title.
        Example: 'Cute Watercolor Christmas Cat Illustration'
        """
        # Split tokens
        tokens = [w for w in re.split(r"[_\-\s]+", theme_hint.strip()) if w]
        clean_words = []
        for t in tokens:
            t_low = t.lower()
            if t_low not in FORBIDDEN_KEYWORDS and len(t) > 1:
                clean_words.append(t.capitalize())

        if not clean_words:
            clean_words = ["Stock", "Asset"]

        # Append natural stock descriptor if space permits
        descriptor = "Graphic" if asset_type == "isolated" else "Scene"
        if len(" ".join(clean_words)) + len(descriptor) + 1 <= max_chars:
            if clean_words[-1].lower() not in ("illustration", "graphic", "photo", "background", "design", "clipart"):
                clean_words.append(descriptor)

        title = " ".join(clean_words)
        title, _ = lint_title(title, max_chars=max_chars)
        return title

    @staticmethod
    def generate_keywords(theme_hint: str, asset_type: str = "isolated", max_count: int = 40) -> List[str]:
        """
        Generate 30 to 45 high-relevance commercial keywords using local thematic taxonomy.
        """
        tokens = [w.lower() for w in re.split(r"[_\-\s]+", theme_hint.strip()) if len(w) > 2]
        keywords: List[str] = []

        # 1. Primary specific tokens
        for t in tokens:
            if t not in FORBIDDEN_KEYWORDS and t not in keywords:
                keywords.append(t)

        # 2. Expand related thematic clusters
        for key, related_list in THEMATIC_EXPANSIONS.items():
            if any(key in t or t in key for t in tokens):
                for rel in related_list:
                    if rel not in keywords and rel not in FORBIDDEN_KEYWORDS:
                        keywords.append(rel)

        # 3. Add asset type specific stock tags
        if asset_type == "isolated":
            type_tags = ["isolated", "white background", "clipart", "sticker", "design element", "graphic", "illustration", "cut out", "print", "card", "decal", "png"]
        else:
            type_tags = ["photograph", "background", "wallpaper", "copy space", "commercial", "high resolution", "composition", "ambient", "texture"]

        for tag in type_tags:
            if tag not in keywords:
                keywords.append(tag)

        # 4. Fill common high-traffic stock utility keywords if below 30
        generic_fillers = ["design", "art", "creative", "concept", "decorative", "modern", "template", "style", "beautiful", "visual", "backdrop", "element", "layout"]
        for f in generic_fillers:
            if len(keywords) >= max_count:
                break
            if f not in keywords:
                keywords.append(f)

        cleaned_kw, _ = lint_keywords(keywords, max_count=max_count)
        return cleaned_kw

