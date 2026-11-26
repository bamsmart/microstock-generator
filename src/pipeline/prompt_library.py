"""
Commercial-Grade Prompt Library for Adobe Stock (Scene + Edge-Safe Isolated Assets).

Contains:
- ISOLATED studio recipe engineered to avoid Adobe Stock "Quality Issues" rejections
  (halo/fringe, gray gradient backgrounds, noisy white space, soft edges, messy shadows, cropped subjects).
- Edge-risk subject detector (glass, fur, smoke, condensation, tassels, etc. that break clean cutouts).
- Negative prompts for generators that support them (Firefly "Exclude", Flux/SD negative, Midjourney --no).
- Evergreen high-demand niche rotation for daily variety.
- Offline combinatorial subject library (fallback when no LLM key) with stable variant keys for anti-repeat.
"""

import re
from datetime import date
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Isolated (cutout) studio recipe — research-based (Adobe Stock quality standards)
# ---------------------------------------------------------------------------
ISOLATED_RECIPE_PARTS: List[Tuple[Tuple[str, ...], str]] = [
    (("#ffffff", "white background"), "isolated on a seamless pure white background (#FFFFFF)"),
    (("zero gradient", "no gradient"), "evenly lit background with zero gradient and zero vignette"),
    (("opaque",), "solid opaque subject with a well-defined silhouette and strong tonal contrast against the white"),
    (("rim light", "edge light"), "large softbox key light with a subtle rim light separating every edge from the background"),
    (("f/11", "edge-to-edge"), "shot with a 100mm macro lens at f/11 for edge-to-edge sharp focus, no depth-of-field blur"),
    (("uncropped", "fully in frame"), "centered and fully in frame, full uncropped silhouette with about 12% clean margin on all sides"),
    (("no drop shadow", "no cast shadow"), "no drop shadows, no cast shadows, no floor reflection"),
    (("noise-free", "no grain"), "clean noise-free surfaces with natural micro-texture, no grain, no blur"),
    (("no floating", "no loose"), "no floating particles, no loose fragments, no props"),
]

# Subjects/materials whose edges break automatic background removal (halo, gaps, fringing)
ISOLATED_EDGE_RISK_TERMS = {
    "glass": "transparent glass edges", "transparent": "transparency", "translucent": "translucency",
    "frosted": "frosted/translucent material", "crystal": "transparent crystal", "condensation": "condensation droplets",
    "droplet": "water droplets", "droplets": "water droplets", "ice cube": "ice cubes", "ice cubes": "ice cubes",
    "steam": "steam wisps", "smoke": "smoke wisps", "mist": "mist", "vapor": "vapor", "splash": "liquid splash",
    "bubbles": "bubbles", "fur": "fur strands", "furry": "fur strands", "feather": "feathers", "feathers": "feathers",
    "hair": "hair strands", "wisps": "fine wisps", "tassel": "tassels", "tassels": "tassels", "fringe": "fringe",
    "lace": "lace holes", "mesh": "mesh holes", "sheer": "sheer fabric", "tulle": "tulle", "string": "thin strings",
    "thread": "thin threads", "glitter": "glitter specks", "sparkles": "sparkles", "confetti": "confetti",
    "sprinkles": "sprinkles", "crumbs": "crumbs", "petals scattered": "scattered petals", "scattered": "scattered debris",
    "bokeh": "bokeh blur", "watercolor": "watercolor paper bleed", "dandelion": "fluffy seeds", "cotton candy": "fuzzy edges",
    "spider web": "web strands", "fishing line": "thin lines", "wire": "thin wires", "chain": "thin chains",
}

NEGATIVE_PROMPT_ISOLATED = (
    "shadow, cast shadow, drop shadow, gradient background, gray background, vignette, halo, fringe, soft edges, "
    "blur, depth of field, noise, grain, jpeg artifacts, cropped, cut off, out of frame, props, text, letters, "
    "logo, watermark, glass, transparency, smoke, steam, fur, hair strands, floating particles, reflection"
)

NEGATIVE_PROMPT_SCENE = (
    "text, letters, logo, watermark, signature, people faces, hands, distorted anatomy, blur, noise, grain, "
    "jpeg artifacts, oversaturated, overprocessed, plastic look, cluttered composition, cropped subject"
)

# Rotating evergreen high-demand niches (adds daily variety on top of the seasonal window)
EVERGREEN_NICHES: List[str] = [
    "healthy food ingredients and meal prep", "home office productivity and remote work", "skincare and clean beauty products",
    "personal finance, savings and budgeting", "sustainable living and zero-waste household", "minimalist interior design details",
    "coffee and specialty cafe culture", "fitness gear and home workout", "e-commerce shipping, packaging and delivery",
    "education, back to school and online learning", "small business and entrepreneurship tools", "baking and dessert making",
    "gardening, houseplants and seedlings", "travel essentials and vacation planning", "3D clay icons for apps and websites",
    "abstract premium textures and backgrounds", "kitchenware and cooking utensils", "pet care products",
    "medical, pharmacy and wellness supplies", "renewable energy and eco technology", "festive tableware and party supplies",
    "spa, aromatherapy and self-care rituals", "stationery, planners and desk organization", "fresh fruit and vegetable produce",
]


def daily_niche_rotation(today: Optional[date] = None, n: int = 3) -> List[str]:
    """Deterministic daily rotation so consecutive days explore different evergreen niches."""
    ref = today or date.today()
    start = (ref.toordinal() * n) % len(EVERGREEN_NICHES)
    return [EVERGREEN_NICHES[(start + i) % len(EVERGREEN_NICHES)] for i in range(n)]


def assess_isolation_risk(prompt: str) -> List[str]:
    """Return list of edge-risk reasons for an isolated prompt (empty = cutout-safe)."""
    low = (prompt or "").lower()
    # Ignore the risk words when they appear in negations like "no smoke" / "without glass"
    low = re.sub(r"\b(?:no|without)\s+[a-z\- ]{0,25}?(?=,|$)", " ", low)
    hits: List[str] = []
    for term, reason in ISOLATED_EDGE_RISK_TERMS.items():
        if re.search(rf"\b{re.escape(term)}\b", low) and reason not in hits:
            hits.append(reason)
    return hits


# ---------------------------------------------------------------------------
# Offline combinatorial library (fallback when no LLM key is configured)
# months: [] = evergreen, otherwise preferred calendar months (1-12)
# ---------------------------------------------------------------------------
ISOLATED_SUBJECTS: List[Dict] = [
    {"subject": "matte sage green ceramic coffee mug", "buyer": "Cafe menus, kitchenware e-commerce", "months": []},
    {"subject": "ripe red apple with a single green leaf", "buyer": "Grocery, nutrition, education", "months": [8, 9, 10]},
    {"subject": "stack of three hardcover books in navy, mustard and forest green", "buyer": "Education, bookstores, back to school", "months": [7, 8]},
    {"subject": "cognac brown leather wallet", "buyer": "Fashion accessories, Father's Day, finance", "months": [5, 6]},
    {"subject": "halved ripe avocado with the pit", "buyer": "Healthy food, recipe apps, nutrition", "months": []},
    {"subject": "golden butter croissant", "buyer": "Bakery, breakfast menus, food delivery", "months": []},
    {"subject": "black cast iron skillet", "buyer": "Kitchenware stores, cooking blogs", "months": [10, 11]},
    {"subject": "gift box wrapped in kraft paper with a wide red satin ribbon bow", "buyer": "Holiday sales, gift shops", "months": [11, 12]},
    {"subject": "round red paper lantern with smooth curved ribs", "buyer": "Lunar New Year promos, greeting cards", "months": [1, 2]},
    {"subject": "polished gold crescent moon ornament", "buyer": "Ramadan & Eid campaigns, greeting cards", "months": [2, 3]},
    {"subject": "ceramic bowl filled with glossy medjool dates", "buyer": "Ramadan F&B promos, healthy snacks", "months": [2, 3]},
    {"subject": "heart-shaped deep red gift box with lid", "buyer": "Valentine's Day promotions, gift brands", "months": [1, 2]},
    {"subject": "3D clay security shield icon in navy with a gold check mark", "buyer": "Fintech apps, cybersecurity sites", "months": []},
    {"subject": "3D clay light bulb icon in warm yellow", "buyer": "Startup decks, idea and innovation concepts", "months": []},
    {"subject": "3D clay piggy bank in coral pink with a gold coin", "buyer": "Banking, savings, personal finance apps", "months": [1, 4]},
    {"subject": "3D clay calendar icon with a red binding", "buyer": "Scheduling apps, planners, HR tools", "months": [12, 1]},
    {"subject": "matte stainless steel insulated water bottle", "buyer": "Fitness, hydration, eco products", "months": [5, 6, 7]},
    {"subject": "hand-painted pastel easter eggs in a neat cluster", "buyer": "Easter retail, greeting cards", "months": [3, 4]},
    {"subject": "brown corrugated cardboard shipping box with closed flaps", "buyer": "E-commerce, logistics, delivery apps", "months": [11, 12]},
    {"subject": "kraft paper shopping bag with folded paper handles", "buyer": "Retail sales, Black Friday, eco packaging", "months": [10, 11]},
    {"subject": "3D clay green four-leaf clover", "buyer": "St. Patrick's Day promos, luck concepts", "months": [2, 3]},
    {"subject": "galvanized metal watering can", "buyer": "Garden centers, spring campaigns", "months": [3, 4, 5]},
    {"subject": "yellow safety hard hat", "buyer": "Construction, engineering, industry", "months": []},
    {"subject": "white desktop calculator with gray buttons on a dark slate tray", "buyer": "Tax season, accounting, finance", "months": [2, 3, 4]},
    {"subject": "terracotta pot with a compact jade succulent", "buyer": "Houseplant shops, interior decor", "months": [3, 4]},
    {"subject": "orange pumpkin with a curled green stem", "buyer": "Autumn & Halloween retail", "months": [9, 10]},
    {"subject": "glossy dark chocolate bar segment block", "buyer": "Confectionery, Valentine's, desserts", "months": [1, 2]},
    {"subject": "wooden serving board with a handle", "buyer": "Kitchenware, food styling, restaurants", "months": []},
]

ISOLATED_VARIANTS: List[Tuple[str, str]] = [
    ("front", "straight front view at eye level"),
    ("tq", "three-quarter view from slightly above"),
    ("elev", "elevated 30-degree product view"),
]

SCENE_SUBJECTS: List[Dict] = [
    {"subject": "minimalist oak desk with a closed linen notebook and ceramic mug", "buyer": "SaaS, productivity, business decks", "months": [1, 8, 9]},
    {"subject": "overhead flatlay of fresh salad ingredients on a pale stone counter", "buyer": "Recipe apps, nutrition, grocery", "months": [1, 5, 6]},
    {"subject": "travertine stone podium with a palm leaf shadow on a beige plaster wall", "buyer": "Cosmetic brands, product mockups", "months": []},
    {"subject": "festive Ramadan table with a brass lantern and bowl of dates on travertine", "buyer": "Ramadan & Eid F&B campaigns", "months": [2, 3]},
    {"subject": "Lunar New Year table with plain red envelopes, mandarins and gold coins", "buyer": "Lunar New Year retail promos", "months": [1, 2]},
    {"subject": "Valentine's breakfast tray with heart-shaped pancakes and fresh berries", "buyer": "Valentine's food & gift promos", "months": [1, 2]},
    {"subject": "spa still life with rolled linen towels, river stones and eucalyptus sprigs", "buyer": "Wellness, spa, self-care brands", "months": []},
    {"subject": "spring seedlings in biodegradable pots on a sunny windowsill", "buyer": "Gardening, eco brands, spring campaigns", "months": [3, 4]},
    {"subject": "rooftop solar panels under a clear blue sky", "buyer": "ESG reports, clean energy companies", "months": [3, 4]},
    {"subject": "kraft shipping boxes stacked beside a packing tape dispenser on a wooden table", "buyer": "E-commerce, logistics, small business", "months": [10, 11]},
    {"subject": "cozy reading nook with a knitted blanket and steaming tea cup", "buyer": "Lifestyle, hygge, home decor", "months": [10, 11, 12]},
    {"subject": "pastel easter eggs in a ceramic bowl on soft linen", "buyer": "Easter retail, greeting cards", "months": [3, 4]},
    {"subject": "neatly organized pantry shelves with glass jars of grains and pasta", "buyer": "Home organization, spring cleaning", "months": [3, 4]},
    {"subject": "personal budget planner with a calculator, coins and a pen on a white desk", "buyer": "Tax season, personal finance", "months": [2, 3, 4]},
    {"subject": "freshly baked sourdough loaf on a flour-dusted wooden board", "buyer": "Bakeries, recipe blogs", "months": []},
    {"subject": "abstract layered paper waves in soft gradient tones", "buyer": "Presentation & website backgrounds", "months": []},
    {"subject": "modern bright kitchen counter with a fruit bowl and marble backsplash", "buyer": "Real estate, interior brands", "months": []},
    {"subject": "back to school flatlay of notebooks, pencils and an apple on a wooden desk", "buyer": "Education, retail back-to-school", "months": [7, 8]},
    {"subject": "summer iced coffee on a sunlit cafe table with dappled shadows", "buyer": "Cafes, beverage summer promos", "months": [5, 6, 7]},
    {"subject": "home workout corner with a yoga mat, dumbbells and a water bottle", "buyer": "Fitness apps, sportswear", "months": [1, 6, 7]},
    {"subject": "Christmas gift boxes in kraft paper with evergreen sprigs on a wooden table", "buyer": "Holiday retail, greeting cards", "months": [11, 12]},
    {"subject": "St. Patrick's Day table with shamrock-shaped cookies and green napkins", "buyer": "Seasonal F&B and party promos", "months": [2, 3]},
]

SCENE_VARIANTS: List[Tuple[str, str]] = [
    ("ovl", "overhead flatlay composition, clean negative copy space on the left third"),
    ("45r", "45-degree editorial angle, clean negative copy space on the right third"),
    ("eyt", "eye-level shallow depth of field, clean negative copy space in the upper third"),
]


def _rank_by_months(items: List[Dict], target_months: List[int], rotation_seed: int) -> List[Dict]:
    seasonal = [i for i in items if any(m in i["months"] for m in target_months)]
    evergreen = [i for i in items if not i["months"]]
    others = [i for i in items if i not in seasonal and i not in evergreen]

    def rotate(lst: List[Dict]) -> List[Dict]:
        if not lst:
            return lst
        k = rotation_seed % len(lst)
        return lst[k:] + lst[:k]

    return rotate(seasonal) + rotate(evergreen) + rotate(others)


def build_offline_isolated_prompt(subject: str, view: str) -> str:
    return (
        f"Professional studio product photograph of a {subject}, {view}, "
        "isolated on a seamless pure white background (#FFFFFF), evenly lit background with zero gradient and zero vignette, "
        "solid opaque subject with a well-defined silhouette and strong tonal contrast against the white, "
        "large softbox key light with a subtle rim light separating every edge from the background, "
        "shot with a 100mm macro lens at f/11 for edge-to-edge sharp focus, "
        "centered and fully in frame, full uncropped silhouette with about 12% clean margin on all sides, "
        "no drop shadows, no cast shadows, no floor reflection, clean noise-free surfaces with natural micro-texture, "
        "no props, no text, no logos, no watermarks"
    )


def build_offline_scene_prompt(subject: str, composition: str) -> str:
    return (
        f"Commercial editorial photograph of a {subject}, {composition}, "
        "soft natural window daylight, authentic surface micro-textures, realistic editorial color grading, "
        "shot on a 50mm prime lens, balanced uncluttered composition with clear commercial utility, "
        "no people, no text, no logos, no watermarks"
    )


def generate_offline_candidates(
    asset_type: str,
    target_months: List[int],
    rotation_seed: int,
) -> List[Dict]:
    """Yield ordered offline candidates (seasonal first) with stable variant_key for anti-repeat tracking."""
    if asset_type == "isolated":
        subjects, variants, builder = ISOLATED_SUBJECTS, ISOLATED_VARIANTS, build_offline_isolated_prompt
    else:
        subjects, variants, builder = SCENE_SUBJECTS, SCENE_VARIANTS, build_offline_scene_prompt

    ranked = _rank_by_months(subjects, target_months, rotation_seed)
    candidates: List[Dict] = []
    # Variant-major ordering: every subject appears once before any subject repeats with a new angle
    for v_idx in range(len(variants)):
        v_code, v_text = variants[(v_idx + rotation_seed) % len(variants)]
        for item in ranked:
            slug = re.sub(r"[^a-z0-9]+", "_", item["subject"].lower()).strip("_")
            candidates.append({
                "asset_type": asset_type,
                "aspect_ratio": "1:1" if asset_type == "isolated" else "3:2",
                "subject": item["subject"],
                "theme": item["subject"].title()[:60],
                "buyer": item["buyer"],
                "folder_slug": slug[:24].rstrip("_"),
                "variant_key": f"{asset_type}:{slug}:{v_code}",
                "prompt": builder(item["subject"], v_text),
            })
    return candidates
