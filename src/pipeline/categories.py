"""
Adobe Stock Official Categories (IDs 1 to 21).
Required for bulk CSV metadata upload:
https://helpx.adobe.com/stock/contributor/help/csv-metadata.html
"""

from typing import Dict, Optional

ADOBE_STOCK_CATEGORIES: Dict[int, str] = {
    1: "Animals",
    2: "Buildings and Architecture",
    3: "Business",
    4: "Drinks",
    5: "The Environment",
    6: "States of Mind",
    7: "Food",
    8: "Graphic Resources",
    9: "Hobbies and Leisure",
    10: "Industry",
    11: "Landscapes",
    12: "Lifestyle",
    13: "People",
    14: "Plants and Flowers",
    15: "Culture and Religion",
    16: "Science",
    17: "Social Issues",
    18: "Sports",
    19: "Technology",
    20: "Transport",
    21: "Travel"
}

CATEGORY_NAME_TO_ID: Dict[str, int] = {
    name.lower(): cat_id for cat_id, name in ADOBE_STOCK_CATEGORIES.items()
}


def normalize_category_id(category: Optional[str or int]) -> int:
    """Resolve category name or ID to a valid Adobe Stock category ID (1-21). Default: 8 (Graphic Resources)."""
    if category is None:
        return 8
    if isinstance(category, int) and 1 <= category <= 21:
        return category
    if isinstance(category, str):
        cleaned = category.strip().lower()
        if cleaned.isdigit():
            val = int(cleaned)
            if 1 <= val <= 21:
                return val
        if cleaned in CATEGORY_NAME_TO_ID:
            return CATEGORY_NAME_TO_ID[cleaned]
        for name, cat_id in CATEGORY_NAME_TO_ID.items():
            if cleaned in name or name in cleaned:
                return cat_id
    return 8  # Fallback to Graphic Resources

