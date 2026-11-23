"""
High-Demand Microstock Research & Commercial-Grade Prompt Engine (Step 1).

Combines:
1. H-60 to H-90 Seasonal Buyer Demand Calendar (what buyers search 2-3 months ahead)
2. Live Google Trends RSS signals (graceful offline fallback)
3. Evergreen High-Converting Adobe Stock Niches (zero trademark/copyright risk)
4. Free-Tier LLM synthesis (Groq -> Gemini Flash -> Mistral -> OpenRouter :free)
   with curated commercial-grade offline blueprints when no API key is set.

Outputs copy-paste ready prompt packs (.txt and .json) for Step 2 manual generation.
"""

import json
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .compliance import FORBIDDEN_KEYWORDS, lint_commercial_prompt, sanitize_filename
from .llm_router import FreeTierLLMRouter, build_ssl_context

# Monthly buyer-demand calendar (indexed by TARGET month, i.e., 2-3 months ahead of today)
SEASONAL_DEMAND_CALENDAR: Dict[int, List[Dict[str, str]]] = {
    1: [
        {"theme": "Q1 Corporate Finance & Fresh Start Goals", "buyer": "SaaS, fintech, consulting decks", "category": "Business"},
        {"theme": "Winter Wellness, Mindfulness & Detox", "buyer": "Health blogs, wellness apps, supplements", "category": "Lifestyle"},
    ],
    2: [
        {"theme": "Lunar New Year Festive Gold & Red Elements", "buyer": "Retail promos, greeting cards, e-commerce banners", "category": "Culture and Religion"},
        {"theme": "Valentine's Day Minimalist Romance & Botanicals", "buyer": "Florists, gift brands, social ads", "category": "Lifestyle"},
        {"theme": "Ramadan & Islamic Geometric Lantern Aesthetics", "buyer": "Regional e-commerce, hospitality, greeting campaigns", "category": "Culture and Religion"},
    ],
    3: [
        {"theme": "Spring Botanicals, Blooming Florals & Pastel Textures", "buyer": "Cosmetics, packaging, print-on-demand", "category": "Plants and Flowers"},
        {"theme": "Eid Mubarak Festive Crescent, Dates & Luxury Tableware", "buyer": "F&B promos, greeting cards, retail banners", "category": "Culture and Religion"},
        {"theme": "International Women's Day & Diverse Leadership", "buyer": "Corporate HR, editorial, NGO campaigns", "category": "People"},
        {"theme": "ESG Sustainability, Green Energy & Eco Packaging", "buyer": "Annual reports, clean-tech startups", "category": "The Environment"},
    ],
    4: [
        {"theme": "Earth Day, Renewable Energy & Circular Economy", "buyer": "Corporate ESG reports, green brands", "category": "The Environment"},
        {"theme": "Easter Pastel Crafts & Spring Picnic Flatlays", "buyer": "Retail, food blogs, stationery", "category": "Food"},
    ],
    5: [
        {"theme": "Mother's Day Luxury Floral Arrangements & Soft Pastel", "buyer": "Gift shops, beauty brands, cards", "category": "Plants and Flowers"},
        {"theme": "Outdoor Summer Travel Prep & Minimalist Luggage", "buyer": "Travel agencies, airlines, lifestyle blogs", "category": "Travel"},
    ],
    6: [
        {"theme": "Summer Tropical Drinks, Iced Coffee & Sunlit Shadows", "buyer": "Cafes, beverage brands, summer ads", "category": "Drinks"},
        {"theme": "Remote Work & Digital Nomad Coastal Workspace", "buyer": "Tech companies, productivity apps", "category": "Business"},
    ],
    7: [
        {"theme": "Mid-Year Sales, E-Commerce 3D Icons & Podiums", "buyer": "Online stores, UI designers, marketers", "category": "Graphic Resources"},
        {"theme": "Summer Fitness, Hydration & Outdoor Wellness", "buyer": "Sportswear, nutrition brands", "category": "Sports"},
    ],
    8: [
        {"theme": "Back to School Flatlays, Stationery & EdTech", "buyer": "Education platforms, retail back-to-school", "category": "Business"},
        {"theme": "Early Autumn Warm Aesthetic & Organic Harvest", "buyer": "F&B, home decor, seasonal blogs", "category": "Food"},
    ],
    9: [
        {"theme": "Autumn Cozy Interiors, Warm Knitwear & Coffee", "buyer": "Interior brands, hospitality, magazines", "category": "Lifestyle"},
        {"theme": "Cybersecurity, Cloud AI & Enterprise Data Visuals", "buyer": "B2B SaaS, tech blogs, keynote decks", "category": "Technology"},
    ],
    10: [
        {"theme": "Halloween Cute Watercolor & Editorial Autumn Decor", "buyer": "POD, party planners, retail banners", "category": "Graphic Resources"},
        {"theme": "Mental Health Awareness & Calm Minimalist Spaces", "buyer": "Healthcare, HR wellness, therapy apps", "category": "Science"},
    ],
    11: [
        {"theme": "Black Friday & Cyber Monday Luxury Product Podiums", "buyer": "E-commerce ads, hero banners", "category": "Graphic Resources"},
        {"theme": "Thanksgiving Harvest Table & Warm Culinary Scenes", "buyer": "Grocery chains, recipe platforms", "category": "Food"},
    ],
    12: [
        {"theme": "Christmas & Winter Holiday Botanicals, Wreaths & Gifts", "buyer": "Retail, greeting cards, packaging", "category": "Graphic Resources"},
        {"theme": "New Year Celebration Gold Bokeh & Minimalist Champagne", "buyer": "Events, hospitality, year-end reports", "category": "Lifestyle"},
    ],
}

# Curated evergreen & seasonal commercial-grade prompt blueprints (offline/fallback quality guarantee)
COMMERCIAL_BLUEPRINTS: List[Dict[str, str]] = [
    {
        "asset_type": "scene",
        "aspect_ratio": "3:2",
        "theme": "Q1 Corporate Finance & Modern Workspace",
        "buyer": "Fintech, SaaS hero banners, business presentations",
        "folder_slug": "q1_minimal_workspace",
        "prompt": (
            "Minimalist Scandinavian sunlit home office desk shot from a 45-degree editorial angle, "
            "warm oak wood tabletop with a clean matte ceramic coffee mug, closed linen notebook, "
            "sleek unbranded silver laptop slightly open, soft morning window light casting gentle diagonal shadows, "
            "generous clean negative copy space on the left third for typography, shallow depth of field, "
            "shot on 50mm prime lens, natural editorial color grading, crisp micro-textures, no text, no logos, no watermarks"
        ),
    },
    {
        "asset_type": "scene",
        "aspect_ratio": "3:2",
        "theme": "ESG Sustainability & Green Energy",
        "buyer": "Corporate ESG reports, clean-tech websites, sustainability campaigns",
        "folder_slug": "esg_green_energy",
        "prompt": (
            "Aerial golden-hour commercial photograph of sleek modern solar panels nestled beside rolling lush green hills "
            "and a clean wind turbine in the far distance under a soft pastel blue sky with light wisps of cloud, "
            "wide negative copy space in the upper sky for headline placement, authentic natural daylight, "
            "crisp architectural sharpness, balanced neutral-warm color palette, no text, no logos, no watermarks"
        ),
    },
    {
        "asset_type": "scene",
        "aspect_ratio": "3:2",
        "theme": "Ramadan & Eid Luxury Hospitality Table",
        "buyer": "Regional retail banners, F&B promotions, festive greeting campaigns",
        "folder_slug": "ramadan_eid_luxury_table",
        "prompt": (
            "Overhead flatlay editorial photograph of an elegant neutral-toned festive table setting on warm travertine stone, "
            "featuring an intricate brass Moroccan lantern glowing softly, a ceramic bowl of fresh Medjool dates, "
            "delicate white jasmine blossoms, and folded cream linen napkin, soft diffused window lighting, "
            "generous clean travertine copy space in the center-right for greeting text, authentic studio shadows, "
            "crisp natural textures, no text, no logos, no watermarks"
        ),
    },
    {
        "asset_type": "scene",
        "aspect_ratio": "3:2",
        "theme": "Minimalist Cosmetic Product Display Podium",
        "buyer": "Skincare brands, e-commerce hero banners, graphic designers",
        "folder_slug": "cosmetic_stone_podium",
        "prompt": (
            "Clean minimalist commercial studio backdrop featuring a geometric matte travertine stone cylindrical podium "
            "standing on a warm beige plaster surface, soft dappled sunlight passing through a monstera leaf casting delicate shadows "
            "on the textured wall behind, abundant clean negative space above and around the podium for product compositing, "
            "soft editorial color grading, crisp focus, no products, no text, no logos, no watermarks"
        ),
    },
    {
        "asset_type": "scene",
        "aspect_ratio": "3:2",
        "theme": "Spring Botanicals & Wellness Spa Flatlay",
        "buyer": "Beauty & wellness brands, aromatherapy, editorial blogs",
        "folder_slug": "spring_wellness_spa",
        "prompt": (
            "Serene overhead flatlay photograph of fresh eucalyptus sprigs, pale pink ranunculus petals, smooth river pebbles, "
            "and a clear glass dropper bottle with unbranded amber oil resting on textured raw cream linen fabric, "
            "soft natural north-facing window light, generous empty linen copy space on the right half for typography, "
            "calm pastel organic palette, sharp studio detail, no text, no labels, no logos, no watermarks"
        ),
    },
    {
        "asset_type": "scene",
        "aspect_ratio": "3:2",
        "theme": "Future AI & Abstract Glassmorphism Data Flow",
        "buyer": "Tech startups, B2B SaaS websites, keynote slide backgrounds",
        "folder_slug": "tech_glass_abstract",
        "prompt": (
            "Ultra-clean modern abstract 3D architectural backdrop of translucent frosted glass ribbons and subtle luminous "
            "indigo and teal light refractions flowing smoothly across a clean off-white studio gradient, "
            "smooth silky surface reflections, ample clean uncluttered negative space on the left for presentation headlines, "
            "minimalist corporate technology aesthetic, crisp studio render quality, no text, no numbers, no logos"
        ),
    },
    {
        "asset_type": "isolated",
        "aspect_ratio": "1:1",
        "theme": "Spring Watercolor Botanical Wreath (Isolated PNG)",
        "buyer": "Wedding invitations, greeting cards, packaging, POD designers",
        "folder_slug": "isolated_spring_botanical",
        "prompt": (
            "Delicate hand-painted botanical watercolor bouquet of blooming cherry blossoms, sage eucalyptus leaves, "
            "and soft blush peonies, rich natural paper pigment texture and fine brushwork detail, "
            "isolated on a pure solid white background (#FFFFFF), centered subject filling 80% of the square frame, "
            "crisp clean outer edges, soft even lighting, no drop shadows, no frame border, no text, no watermark"
        ),
    },
    {
        "asset_type": "isolated",
        "aspect_ratio": "1:1",
        "theme": "Festive Gold Brass Lantern (Isolated PNG)",
        "buyer": "Ramadan/Eid flyers, cultural greeting cards, e-commerce stickers",
        "folder_slug": "isolated_brass_lantern",
        "prompt": (
            "Ornate traditional brushed brass and frosted glass Moroccan decorative lantern with intricate geometric lattice patterns, "
            "realistic metallic specular highlights, front studio view, isolated on a pure solid white background (#FFFFFF), "
            "centered subject filling 80% of frame, sharp distinct edges, even studio lighting, no floor cast shadow, "
            "no text, no logo, no watermark"
        ),
    },
    {
        "asset_type": "isolated",
        "aspect_ratio": "1:1",
        "theme": "3D Clay Eco-Sustainability Icon (Isolated PNG)",
        "buyer": "SaaS landing pages, pitch decks, ESG infographics, UI designers",
        "folder_slug": "isolated_3d_eco_icon",
        "prompt": (
            "Minimalist isometric 3D matte clay icon of a miniature green leaf sprouting from a clean white geometric globe "
            "with soft sage and pastel mint accents, smooth tactile ceramic finish, soft studio global illumination, "
            "isolated on a pure solid white background (#FFFFFF), centered subject filling 78% of frame, "
            "crisp edges, no ground shadow, no text, no logo, no watermark"
        ),
    },
    {
        "asset_type": "isolated",
        "aspect_ratio": "1:1",
        "theme": "Artisanal Iced Matcha Latte Glass (Isolated PNG)",
        "buyer": "Cafe menus, food delivery apps, beverage marketing banners",
        "folder_slug": "isolated_iced_matcha",
        "prompt": (
            "Studio commercial food photograph of a crystal-clear ribbed glass filled with layered vibrant ceremonial green iced matcha latte, "
            "creamy oat milk swirl, clear ice cubes, and tiny condensation droplets on the glass, straight-on eye-level angle, "
            "isolated on a pure solid white background (#FFFFFF), centered subject filling 80% of frame, "
            "razor-sharp clean edges, bright even studio lighting, no cast shadow, no straw logo, no text, no watermark"
        ),
    },
    {
        "asset_type": "isolated",
        "aspect_ratio": "1:1",
        "theme": "Luxury Silk Ribbon Bow (Isolated PNG)",
        "buyer": "Valentine's Day, Mother's Day, luxury gift packaging & e-commerce",
        "folder_slug": "isolated_silk_bow",
        "prompt": (
            "Realistic commercial studio photograph of an elegantly tied champagne-gold satin silk ribbon bow with flowing tapered tails, "
            "delicate fabric weave texture and soft lustrous sheen, flat front view, "
            "isolated on a pure solid white background (#FFFFFF), centered subject filling 80% of frame, "
            "clean sharp silhouette, even softbox lighting, no drop shadow, no text, no watermark"
        ),
    },
    {
        "asset_type": "isolated",
        "aspect_ratio": "1:1",
        "theme": "Minimalist 3D Fintech Shield & Coin Icon (Isolated PNG)",
        "buyer": "Fintech apps, cybersecurity blogs, Q1 finance decks",
        "folder_slug": "isolated_fintech_shield",
        "prompt": (
            "Sleek minimalist 3D frosted glass and brushed matte navy security shield icon with a clean gold checkmark accent, "
            "subtle smooth edge bevels, soft studio lighting, front three-quarter isometric view, "
            "isolated on a pure solid white background (#FFFFFF), centered subject filling 78% of frame, "
            "crisp clean silhouette, no ground shadow, no text, no brand symbols, no watermark"
        ),
    },
]


def _clean_prompt_forbidden(prompt: str, asset_type: str = "scene") -> str:
    """Enforce Adobe Stock commercial-grade prompt compliance (strip banned IP/buzzwords + ensure guardrails)."""
    cleaned, _ = lint_commercial_prompt(prompt, asset_type=asset_type)
    return cleaned


def get_upcoming_seasonal_themes(today: Optional[date] = None) -> Tuple[str, List[Dict[str, str]]]:
    """Return H-60 to H-90 target window description and high-demand themes."""
    ref = today or date.today()
    start_target = ref + timedelta(days=60)
    end_target = ref + timedelta(days=95)

    months = []
    cur = start_target.replace(day=1)
    while cur <= end_target:
        if cur.month not in months:
            months.append(cur.month)
        # advance ~32 days to next month
        cur = (cur + timedelta(days=32)).replace(day=1)

    themes: List[Dict[str, str]] = []
    for m in months:
        themes.extend(SEASONAL_DEMAND_CALENDAR.get(m, []))

    window_label = f"{start_target.strftime('%b %Y')} - {end_target.strftime('%b %Y')}"
    return window_label, themes


def fetch_google_trends_rss(geo: str = "US", max_items: int = 12, timeout: int = 8) -> List[str]:
    """Fetch live trending search topics from Google Trends RSS (100% free, no API key)."""
    url = f"https://trends.google.com/trending/rss?geo={geo}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MicrostockGenerator/2.0"})
        with urllib.request.urlopen(req, timeout=timeout, context=build_ssl_context()) as resp:
            xml_data = resp.read()
        root = ET.fromstring(xml_data)
        titles: List[str] = []
        for item in root.findall(".//item/title"):
            if item.text and item.text.strip():
                t = item.text.strip()
                # Skip obvious brand/person names in forbidden list
                if not any(f in t.lower() for f in FORBIDDEN_KEYWORDS):
                    titles.append(t)
            if len(titles) >= max_items:
                break
        return titles
    except Exception:
        return []


class HighDemandResearcher:
    """Researches high-demand microstock topics and outputs commercial-grade prompts."""

    def __init__(self, llm_router: Optional[FreeTierLLMRouter] = None):
        self.llm = llm_router or FreeTierLLMRouter()

    def run_research(
        self,
        output_dir: Path,
        count: int = 12,
        niche_focus: Optional[str] = None,
        log_callback=print,
    ) -> Dict[str, Any]:
        """
        Execute Step 1 research and export copy-paste ready prompt pack (.txt & .json).
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        window_label, seasonal_themes = get_upcoming_seasonal_themes()
        log_callback(f"📅 Target Buyer Window (H-60 to H-90): {window_label}")
        for st in seasonal_themes:
            log_callback(f"   • {st['theme']} ({st['category']})")

        log_callback("\n🌐 Fetching live Google Trends RSS signals (free)...")
        live_trends = fetch_google_trends_rss(geo="US", max_items=10)
        if live_trends:
            log_callback(f"   ✅ Fetched {len(live_trends)} live trend signals: {', '.join(live_trends[:5])}...")
        else:
            log_callback("   ℹ️ Live RSS unavailable/offline — using H-60..H-90 seasonal + evergreen demand signals.")

        n_scene = count // 2
        n_isolated = count - n_scene

        prompts: List[Dict[str, str]] = []
        provider_used = "offline_commercial_blueprint"

        # Try Free-Tier Cloud LLM if keys are configured
        if self.llm.available_text_providers():
            log_callback(
                f"\n🤖 Synthesizing {count} commercial-grade prompts via Free-Tier LLM "
                f"({', '.join(self.llm.available_text_providers())})..."
            )
            system_prompt = (
                "You are a Top-1% Adobe Stock Creative Director & Commercial Microstock Compliance Specialist. "
                "Generate high-demand, commercial-grade AI image generation prompts engineered to pass Adobe Stock's "
                "strict Technical, Legal/IP, and Commercial Utility moderation on the first try.\n"
                "MANDATORY ADOBE STOCK RULES:\n"
                "1. ZERO IP/LEGAL RISK: Never mention brands, trademarks, logos, copyrighted characters, "
                "recognizable landmarks/modern architecture, newsworthy events, or living/deceased artists (never 'in the style of ...').\n"
                "2. ZERO ANATOMY / RELEASE RISK: Avoid recognizable human faces, celebrities, or complex hand/crowd scenes. "
                "Focus on high-selling commercial subjects: objects, workspaces, interiors, flatlays, food/drinks, botanicals, "
                "product podiums, textures, and minimalist 3D icons.\n"
                "3. ZERO TEXT / WATERMARKS: Always specify 'no text, no logos, no watermarks'.\n"
                "4. ZERO AI PLASTIC BUZZWORDS: Never use '8k', '4k', 'photorealistic', 'hyperrealistic', 'unreal engine', "
                "'octane render', 'masterpiece', 'award winning', or 'trending' — describe real camera optics, natural daylight, "
                "and authentic surface micro-textures instead.\n"
                "5. FOR 'scene' PROMPTS (3:2): Specify natural editorial lighting, lens/angle, authentic textures, clear commercial "
                "buyer utility, and generous clean negative copy space (left/right/top third) for designer headlines.\n"
                "6. FOR 'isolated' PROMPTS (1:1): Specify 'isolated on a pure solid white background (#FFFFFF)', "
                "centered full uncropped silhouette filling 75-80% of frame with clean breathing margin on all 4 sides, "
                "crisp clean outer edges, even softbox lighting, no drop shadows, no floating debris.\n"
                "Respond ONLY in valid JSON with key 'prompts' containing a list of objects:\n"
                '{"prompts": [{"asset_type": "scene"|"isolated", "aspect_ratio": "3:2"|"1:1", '
                '"theme": "...", "buyer": "...", "folder_slug": "short_snake_case", '
                '"filename_slug": "specific_subject_01", "prompt": "..."}]}'
            )

            seasonal_summary = "; ".join(f"{t['theme']} ({t['buyer']})" for t in seasonal_themes)
            trend_summary = ", ".join(live_trends) if live_trends else "N/A"
            niche_line = f"Primary Niche Focus requested by user: {niche_focus}\n" if niche_focus else ""

            user_prompt = (
                f"Target commercial buyer window (2-3 months ahead): {window_label}\n"
                f"Upcoming high-demand seasonal themes: {seasonal_summary}\n"
                f"Current public trend signals (filter strictly for commercial-safe stock concepts only): {trend_summary}\n"
                f"{niche_line}"
                f"Generate exactly {n_scene} 'scene' prompts (3:2) and {n_isolated} 'isolated' prompts (1:1). "
                "Make every prompt vivid, specific, unique, and ready to copy-paste directly into Midjourney, Firefly, or Flux."
            )

            data, provider_used = self.llm.generate_json_text(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                log_callback=log_callback,
            )
            if data and isinstance(data.get("prompts"), list) and len(data["prompts"]) > 0:
                for idx, item in enumerate(data["prompts"][:count], start=1):
                    if not isinstance(item, dict) or not item.get("prompt"):
                        continue
                    a_type = "isolated" if str(item.get("asset_type", "")).lower() == "isolated" else "scene"
                    ext = ".png" if a_type == "isolated" else ".jpg"
                    folder_slug = str(item.get("folder_slug", "stock_batch")).strip().lower().replace(" ", "_")[:24]
                    raw_fn_slug = str(item.get("filename_slug", "")).strip() or f"{folder_slug}_{idx:02d}"
                    suggested_filename = sanitize_filename(raw_fn_slug, ext=ext, max_len=30)
                    prompts.append({
                        "asset_type": a_type,
                        "aspect_ratio": "1:1" if a_type == "isolated" else "3:2",
                        "theme": str(item.get("theme", "Commercial Stock Asset")).strip(),
                        "buyer": str(item.get("buyer", "Commercial marketing & design")).strip(),
                        "folder_slug": folder_slug,
                        "suggested_filename": suggested_filename,
                        "prompt": _clean_prompt_forbidden(str(item["prompt"]), asset_type=a_type),
                    })
                log_callback(f"   ✅ Generated {len(prompts)} prompts via Free-Tier provider: {provider_used}")

        # Fallback to curated commercial blueprints if offline or LLM returned empty
        if not prompts:
            provider_used = "offline_commercial_blueprint"
            log_callback(
                "\nℹ️ No Free-Tier LLM API key found in .env (GROQ_API_KEY / GEMINI_API_KEY / MISTRAL_API_KEY / OPENROUTER_API_KEY)."
            )
            log_callback("   Using curated H-60..H-90 Commercial-Grade Blueprint Engine (Rp 0, ready to copy-paste)...")
            selected = COMMERCIAL_BLUEPRINTS[:count]
            if niche_focus:
                # Prioritize matching blueprints first, then fill remainder
                nf = niche_focus.lower()
                matched = [b for b in COMMERCIAL_BLUEPRINTS if nf in b["theme"].lower() or nf in b["prompt"].lower()]
                others = [b for b in COMMERCIAL_BLUEPRINTS if b not in matched]
                selected = (matched + others)[:count]
            prompts = []
            for idx, item in enumerate(selected, start=1):
                entry = dict(item)
                ext = ".png" if entry["asset_type"] == "isolated" else ".jpg"
                entry["suggested_filename"] = sanitize_filename(f"{entry['folder_slug']}_{idx:02d}", ext=ext, max_len=30)
                entry["prompt"] = _clean_prompt_forbidden(entry["prompt"], asset_type=entry["asset_type"])
                prompts.append(entry)

        # Export copy-paste friendly .txt and structured .json
        ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        txt_path = output_dir / f"prompts_{ts}.txt"
        json_path = output_dir / f"prompts_{ts}.json"

        self._write_copy_paste_txt(txt_path, prompts, window_label, provider_used, niche_focus)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "generated_at": datetime.now().isoformat(),
                    "target_window": window_label,
                    "provider": provider_used,
                    "niche_focus": niche_focus,
                    "prompts": prompts,
                },
                f,
                indent=2,
                ensure_ascii=False,
            )

        log_callback(f"\n📝 Copy-Paste Prompt Pack saved to : {txt_path}")
        log_callback(f"📦 Structured JSON backup saved to : {json_path}")

        return {
            "count": len(prompts),
            "provider": provider_used,
            "target_window": window_label,
            "txt_path": txt_path,
            "json_path": json_path,
            "prompts": prompts,
        }

    @staticmethod
    def _write_copy_paste_txt(
        txt_path: Path,
        prompts: List[Dict[str, str]],
        window_label: str,
        provider: str,
        niche_focus: Optional[str],
    ):
        scenes = [p for p in prompts if p["asset_type"] == "scene"]
        isolated = [p for p in prompts if p["asset_type"] == "isolated"]

        lines = [
            "======================================================================",
            " HIGH-DEMAND COMMERCIAL MICROSTOCK PROMPT PACK (COPY-PASTE READY)",
            f" Generated     : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f" Buyer Window  : {window_label} (H-60 to H-90 Strategy)",
            f" Engine        : {provider}",
            f" Niche Focus   : {niche_focus or 'Auto (Seasonal + Evergreen High-Demand)'}",
            "======================================================================",
            "",
            "HOW TO USE (HYBRID WORKFLOW):",
            " 1. Copy any prompt below into your preferred image generator (Firefly / Midjourney / Flux / Ideogram).",
            " 2. Match the recommended Aspect Ratio (3:2 for Scenes, 1:1 for Isolated PNGs).",
            " 3. Save generated images into: ~/Desktop/microstock_generator/<folder_slug>/raw/",
            " 4. Run Step 4 pipeline: python main.py  (Free-Tier Vision QC + SEO Metadata + Upscale + Compliance)",
            "",
        ]

        if scenes:
            lines.append("######################################################################")
            lines.append(f" PART A: FULL-SCENE COMMERCIAL JPEGs ({len(scenes)} Prompts | Aspect Ratio 3:2)")
            lines.append("######################################################################")
            lines.append("")
            for i, p in enumerate(scenes, start=1):
                lines.extend([
                    f"[{i:02d}] {p['theme']}",
                    f"Target Buyer  : {p['buyer']}",
                    f"Batch Folder  : {p['folder_slug']}/raw/",
                    f"Suggested File: {p.get('suggested_filename', '')}  (<= 30 chars, Adobe Stock ready)",
                    f"Aspect Ratio  : {p['aspect_ratio']}",
                    "PROMPT (COPY BELOW):",
                    p["prompt"],
                    "----------------------------------------------------------------------",
                    "",
                ])

        if isolated:
            lines.append("######################################################################")
            lines.append(f" PART B: ISOLATED TRANSPARENT PNGs ({len(isolated)} Prompts | Aspect Ratio 1:1)")
            lines.append("######################################################################")
            lines.append("")
            for i, p in enumerate(isolated, start=1):
                lines.extend([
                    f"[{i:02d}] {p['theme']}",
                    f"Target Buyer  : {p['buyer']}",
                    f"Batch Folder  : {p['folder_slug']}/raw/",
                    f"Suggested File: {p.get('suggested_filename', '')}  (<= 30 chars, Adobe Stock ready)",
                    f"Aspect Ratio  : {p['aspect_ratio']}",
                    "PROMPT (COPY BELOW):",
                    p["prompt"],
                    "----------------------------------------------------------------------",
                    "",
                ])

        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
