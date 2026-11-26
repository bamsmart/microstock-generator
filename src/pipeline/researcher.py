"""
High-Demand Microstock Research & Commercial-Grade Prompt Engine (Step 1).

Combines:
1. H-90 to H-120 Seasonal Buyer Demand Calendar (what buyers license 3-4 months ahead)
2. Daily rotating 24 evergreen commercial verticals + Live Google Trends RSS signals
3. Rolling 120-day Anti-Repeat History (`prompt_history.json`) so daily runs never repeat subjects
4. Edge-Safe Isolated Studio Prompt Rules (prevents Adobe Stock halo/pixel-gap rejections)
5. Free-Tier LLM synthesis (Groq -> Gemini Flash -> Mistral -> OpenRouter :free)
   with curated combinatorial offline commercial library when no API key is set or to top up slots.

Outputs copy-paste ready prompt packs (.txt and .json) with Negative Prompts and <= 30 char filenames.
"""

import json
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .compliance import FORBIDDEN_KEYWORDS, lint_commercial_prompt, sanitize_filename
from .llm_router import FreeTierLLMRouter, build_ssl_context
from .prompt_history import PromptHistory
from .prompt_library import (
    NEGATIVE_PROMPT_ISOLATED,
    NEGATIVE_PROMPT_SCENE,
    assess_isolation_risk,
    daily_niche_rotation,
    generate_offline_candidates,
)

# Monthly buyer-demand calendar (indexed by TARGET month, i.e., 3-4 months ahead of today)
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
        {"theme": "Tax Season, Accounting & Personal Finance", "buyer": "Fintech, tax software, consulting", "category": "Business"},
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
        {"theme": "Halloween Cute Pumpkins & Editorial Autumn Decor", "buyer": "POD, party planners, retail banners", "category": "Graphic Resources"},
        {"theme": "Mental Health Awareness & Calm Minimalist Spaces", "buyer": "Healthcare, HR wellness, therapy apps", "category": "Science"},
    ],
    11: [
        {"theme": "Black Friday & Cyber Monday Luxury Product Podiums", "buyer": "E-commerce ads, hero banners", "category": "Graphic Resources"},
        {"theme": "Thanksgiving Harvest Table & Warm Culinary Scenes", "buyer": "Grocery chains, recipe platforms", "category": "Food"},
    ],
    12: [
        {"theme": "Christmas & Winter Holiday Botanicals, Wreaths & Gifts", "buyer": "Retail, greeting cards, packaging", "category": "Graphic Resources"},
        {"theme": "New Year Celebration Gold Bokeh & Minimalist Tableware", "buyer": "Events, hospitality, year-end reports", "category": "Lifestyle"},
    ],
}


def _clean_prompt_forbidden(prompt: str, asset_type: str = "scene") -> str:
    """Enforce Adobe Stock commercial-grade prompt compliance (strip banned IP/buzzwords + ensure guardrails)."""
    cleaned, _ = lint_commercial_prompt(prompt, asset_type=asset_type)
    return cleaned


def get_upcoming_target_months(
    today: Optional[date] = None,
    min_days: int = 90,
    max_days: int = 120,
) -> List[int]:
    """Return ordered list of target calendar months for the H-min_days to H-max_days (3-4 month) window."""
    ref = today or date.today()
    start_target = ref + timedelta(days=min_days)
    end_target = ref + timedelta(days=max_days)

    months: List[int] = []
    cur = start_target.replace(day=1)
    while cur <= end_target:
        if cur.month not in months:
            months.append(cur.month)
        cur = (cur + timedelta(days=32)).replace(day=1)
    return months


def get_upcoming_seasonal_themes(
    today: Optional[date] = None,
    min_days: int = 90,
    max_days: int = 120,
) -> Tuple[str, List[Dict[str, str]]]:
    """Return H-90 to H-120 (3-4 months ahead) target window description and high-demand themes."""
    ref = today or date.today()
    start_target = ref + timedelta(days=min_days)
    end_target = ref + timedelta(days=max_days)
    months = get_upcoming_target_months(today=ref, min_days=min_days, max_days=max_days)

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
                if not any(f in t.lower() for f in FORBIDDEN_KEYWORDS):
                    titles.append(t)
            if len(titles) >= max_items:
                break
        return titles
    except Exception:
        return []


class HighDemandResearcher:
    """Researches high-demand microstock topics (3-4 months ahead) with 120-day anti-repeat memory."""

    def __init__(self, llm_router: Optional[FreeTierLLMRouter] = None):
        self.llm = llm_router or FreeTierLLMRouter()

    def run_research(
        self,
        output_dir: Path,
        count: int = 12,
        niche_focus: Optional[str] = None,
        horizon_days_min: int = 90,
        horizon_days_max: int = 120,
        history_retention_days: int = 120,
        today: Optional[date] = None,
        log_callback=print,
    ) -> Dict[str, Any]:
        """
        Execute Step 1 research and export copy-paste ready prompt pack (.txt & .json)
        with 120-day anti-repeat protection and edge-safe isolated studio prompt rules.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        ref_today = today or date.today()

        history = PromptHistory(
            output_dir / "prompt_history.json",
            retention_days=history_retention_days,
        )

        window_label, seasonal_themes = get_upcoming_seasonal_themes(
            today=ref_today,
            min_days=horizon_days_min,
            max_days=horizon_days_max,
        )
        target_months = get_upcoming_target_months(
            today=ref_today,
            min_days=horizon_days_min,
            max_days=horizon_days_max,
        )
        rotating_niches = daily_niche_rotation(today=ref_today, n=3)
        recent_avoid = history.recent_subjects(limit=60)

        log_callback(
            f"📅 Target Buyer Window (H-{horizon_days_min} to H-{horizon_days_max} | 3-4 Months Ahead): {window_label}"
        )
        for st in seasonal_themes:
            log_callback(f"   • {st['theme']} ({st['category']})")
        log_callback(f"🔄 Today's Evergreen Verticals : {', '.join(rotating_niches)}")
        log_callback(
            f"🛡️  Anti-Repeat Memory         : {len(history.entries)} subject(s) tracked (last {history_retention_days} days)"
        )

        log_callback("\n🌐 Fetching live Google Trends RSS signals (free)...")
        live_trends = fetch_google_trends_rss(geo="US", max_items=10)
        if live_trends:
            log_callback(f"   ✅ Fetched {len(live_trends)} live trend signals: {', '.join(live_trends[:5])}...")
        else:
            log_callback("   ℹ️ Live RSS unavailable/offline — using H-90..H-120 seasonal + daily evergreen signals.")

        n_scene = count // 2
        n_isolated = count - n_scene

        scene_prompts: List[Dict[str, str]] = []
        isolated_prompts: List[Dict[str, str]] = []
        session_entries: List[Dict[str, Any]] = []
        provider_used = "offline_commercial_library"

        # 1. Try Free-Tier Cloud LLM if keys are configured
        if self.llm.available_text_providers():
            log_callback(
                f"\n🤖 Synthesizing {count} unique commercial-grade prompts via Free-Tier LLM "
                f"({', '.join(self.llm.available_text_providers())})..."
            )
            system_prompt = (
                "You are a Top-1% Adobe Stock Creative Director & Commercial Microstock Compliance Specialist. "
                "Generate high-demand, commercial-grade AI image generation prompts engineered to pass Adobe Stock's "
                "strict Technical, Legal/IP, and Quality moderation at 100% zoom on the first try.\n"
                "MANDATORY ADOBE STOCK RULES:\n"
                "1. ZERO IP/LEGAL RISK: Never mention brands, trademarks, logos, copyrighted characters, "
                "recognizable landmarks/modern architecture, newsworthy events, or living/deceased artists (never 'in the style of ...').\n"
                "2. ZERO ANATOMY / RELEASE RISK: Avoid recognizable human faces, celebrities, or complex hand/crowd scenes.\n"
                "3. ZERO TEXT / WATERMARKS: Always specify 'no text, no logos, no watermarks'.\n"
                "4. ZERO AI PLASTIC BUZZWORDS: Never use '8k', '4k', 'photorealistic', 'hyperrealistic', 'unreal engine', "
                "'octane render', 'masterpiece', 'award winning', or 'trending' — describe real camera optics, natural daylight, "
                "and authentic surface micro-textures instead.\n"
                "5. FOR 'scene' PROMPTS (3:2): Specify natural editorial lighting, 50mm prime lens, authentic textures, clear commercial "
                "buyer utility, and generous clean negative copy space (left/right/upper third) for designer headlines.\n"
                "6. FOR 'isolated' PROMPTS (1:1 — CRITICAL QUALITY GUARDRAILS TO PREVENT HALOS & PIXEL GAPS):\n"
                "   - Subject MUST be solid, OPAQUE, medium-to-dark or rich-colored with crisp edges (matte ceramics, leather, "
                "wood, cast iron, opaque fruit/bakery, hardcover books, kraft boxes, brass ornaments, matte 3D clay icons, succulents).\n"
                "   - STRICTLY FORBIDDEN for isolated subjects: transparent/frosted glass, ice cubes, water droplets/condensation, "
                "steam, smoke, mist, fur, hair, feathers, tassels, lace, mesh, thin strings, watercolor bleed, glitter, confetti, "
                "or white-on-white objects.\n"
                "   - MUST specify: 'isolated on a seamless pure white background (#FFFFFF), evenly lit background with zero gradient "
                "and zero vignette, solid opaque subject with strong tonal contrast against the white, large softbox key light with a "
                "subtle rim light separating every edge, shot with a 100mm macro lens at f/11 for edge-to-edge sharp focus, centered "
                "full uncropped silhouette with 12% clean margin on all sides, no drop shadows, no cast shadows, no floor reflection, "
                "clean noise-free surfaces, no floating particles, no props, no text, no logos, no watermarks'.\n"
                "Respond ONLY in valid JSON with key 'prompts' containing a list of objects:\n"
                '{"prompts": [{"asset_type": "scene"|"isolated", "aspect_ratio": "3:2"|"1:1", '
                '"subject": "concise 3-6 word subject name", "theme": "...", "buyer": "...", '
                '"folder_slug": "short_snake_case", "filename_slug": "specific_subject_01", "prompt": "..."}]}'
            )

            seasonal_summary = "; ".join(f"{t['theme']} ({t['buyer']})" for t in seasonal_themes)
            trend_summary = ", ".join(live_trends) if live_trends else "N/A"
            niche_line = f"Primary Niche Focus requested by user: {niche_focus}\n" if niche_focus else ""
            avoid_line = (
                "DO NOT REPEAT or closely resemble ANY of these previously generated subjects from the last 120 days:\n"
                + "; ".join(recent_avoid)
                + "\n"
                if recent_avoid
                else ""
            )

            user_prompt = (
                f"Target commercial buyer window (3-4 months ahead, H-{horizon_days_min} to H-{horizon_days_max}): {window_label}\n"
                f"Upcoming high-demand seasonal themes: {seasonal_summary}\n"
                f"Today's rotating evergreen commercial verticals: {', '.join(rotating_niches)}\n"
                f"Current public trend signals (commercial-safe concepts only): {trend_summary}\n"
                f"{niche_line}"
                f"{avoid_line}"
                f"Generate exactly {n_scene} 'scene' prompts (3:2) and {n_isolated} 'isolated' prompts (1:1). "
                "Every single prompt must cover a distinct, specific, never-repeated commercial subject."
            )

            data, provider_used = self.llm.generate_json_text(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                log_callback=log_callback,
            )
            if data and isinstance(data.get("prompts"), list) and len(data["prompts"]) > 0:
                for idx, item in enumerate(data["prompts"], start=1):
                    if not isinstance(item, dict) or not item.get("prompt"):
                        continue
                    a_type = "isolated" if str(item.get("asset_type", "")).lower() == "isolated" else "scene"
                    target_bucket = isolated_prompts if a_type == "isolated" else scene_prompts
                    target_limit = n_isolated if a_type == "isolated" else n_scene
                    if len(target_bucket) >= target_limit:
                        continue

                    raw_prompt = str(item["prompt"]).strip()
                    subject = str(item.get("subject") or item.get("theme") or "commercial subject").strip()
                    theme = str(item.get("theme") or subject.title()).strip()

                    # Reject edge-risk isolated subjects (glass, fur, steam, droplets, etc.)
                    if a_type == "isolated":
                        risks = assess_isolation_risk(f"{subject} {raw_prompt}")
                        if risks:
                            log_callback(
                                f"   ⚠️ Skipped edge-risk isolated prompt '{subject}' ({', '.join(risks)})"
                            )
                            continue

                    # Reject repeats against 120-day rolling history and current session
                    if history.is_duplicate(subject, theme, raw_prompt, a_type, extra_pool=session_entries):
                        log_callback(f"   ⏭️  Skipped repeat prompt '{subject}' (already generated in last {history_retention_days} days)")
                        continue

                    ext = ".png" if a_type == "isolated" else ".jpg"
                    folder_slug = str(item.get("folder_slug", "stock_batch")).strip().lower().replace(" ", "_")[:24]
                    raw_fn_slug = str(item.get("filename_slug", "")).strip() or f"{folder_slug}_{idx:02d}"
                    suggested_filename = sanitize_filename(raw_fn_slug, ext=ext, max_len=30)
                    cleaned_prompt = _clean_prompt_forbidden(raw_prompt, asset_type=a_type)

                    target_bucket.append({
                        "asset_type": a_type,
                        "aspect_ratio": "1:1" if a_type == "isolated" else "3:2",
                        "subject": subject,
                        "theme": theme,
                        "buyer": str(item.get("buyer", "Commercial marketing & design")).strip(),
                        "folder_slug": folder_slug,
                        "suggested_filename": suggested_filename,
                        "prompt": cleaned_prompt,
                        "negative_prompt": NEGATIVE_PROMPT_ISOLATED if a_type == "isolated" else NEGATIVE_PROMPT_SCENE,
                    })
                    session_entries.append(history.make_entry(subject, theme, raw_prompt, a_type))

                log_callback(
                    f"   ✅ Accepted {len(scene_prompts) + len(isolated_prompts)} unique prompt(s) via Free-Tier provider: {provider_used}"
                )

        # 2. Top up any remaining slots (or full offline generation) with anti-repeat combinatorial library
        need_scene = n_scene - len(scene_prompts)
        need_isolated = n_isolated - len(isolated_prompts)
        if need_scene > 0 or need_isolated > 0:
            if not scene_prompts and not isolated_prompts:
                provider_used = "offline_commercial_library"
                log_callback(
                    "\nℹ️ Using curated H-90..H-120 Commercial Library + 120-Day Anti-Repeat Engine (Rp 0, edge-safe isolated)..."
                )
            else:
                log_callback(
                    f"\nℹ️ Topping up {need_scene + need_isolated} remaining slot(s) from edge-safe H-90..H-120 library..."
                )

            rotation_seed = ref_today.toordinal()
            for a_type, bucket, needed in (
                ("scene", scene_prompts, need_scene),
                ("isolated", isolated_prompts, need_isolated),
            ):
                if needed <= 0:
                    continue
                candidates = generate_offline_candidates(a_type, target_months, rotation_seed)
                if niche_focus:
                    nf = niche_focus.lower()
                    matched = [c for c in candidates if nf in c["subject"].lower() or nf in c["buyer"].lower()]
                    others = [c for c in candidates if c not in matched]
                    candidates = matched + others

                added = 0
                for cand in candidates:
                    if added >= needed:
                        break
                    if history.is_duplicate(
                        cand["subject"],
                        cand["theme"],
                        cand["prompt"],
                        a_type,
                        variant_key=cand["variant_key"],
                        extra_pool=session_entries,
                    ):
                        continue
                    ext = ".png" if a_type == "isolated" else ".jpg"
                    idx_num = len(bucket) + 1
                    entry_out = {
                        "asset_type": a_type,
                        "aspect_ratio": cand["aspect_ratio"],
                        "subject": cand["subject"],
                        "theme": cand["theme"],
                        "buyer": cand["buyer"],
                        "folder_slug": cand["folder_slug"],
                        "suggested_filename": sanitize_filename(
                            f"{cand['folder_slug']}_{idx_num:02d}", ext=ext, max_len=30
                        ),
                        "prompt": _clean_prompt_forbidden(cand["prompt"], asset_type=a_type),
                        "negative_prompt": NEGATIVE_PROMPT_ISOLATED if a_type == "isolated" else NEGATIVE_PROMPT_SCENE,
                    }
                    bucket.append(entry_out)
                    session_entries.append(
                        history.make_entry(
                            cand["subject"],
                            cand["theme"],
                            cand["prompt"],
                            a_type,
                            variant_key=cand["variant_key"],
                        )
                    )
                    added += 1

        # Persist accepted prompts into 120-day rolling anti-repeat history
        for hist_entry in session_entries:
            history.add(hist_entry)
        history.save()

        prompts = scene_prompts + isolated_prompts

        # Export copy-paste friendly .txt and structured .json
        ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        txt_path = output_dir / f"prompts_{ts}.txt"
        json_path = output_dir / f"prompts_{ts}.json"

        self._write_copy_paste_txt(
            txt_path=txt_path,
            prompts=prompts,
            window_label=window_label,
            horizon_min=horizon_days_min,
            horizon_max=horizon_days_max,
            history_count=len(history.entries),
            retention_days=history_retention_days,
            provider=provider_used,
            niche_focus=niche_focus,
        )
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "generated_at": datetime.now().isoformat(),
                    "target_window": window_label,
                    "horizon_days": [horizon_days_min, horizon_days_max],
                    "provider": provider_used,
                    "niche_focus": niche_focus,
                    "history_count": len(history.entries),
                    "prompts": prompts,
                },
                f,
                indent=2,
                ensure_ascii=False,
            )

        log_callback(f"\n📝 Copy-Paste Prompt Pack saved to : {txt_path}")
        log_callback(f"📦 Structured JSON backup saved to : {json_path}")
        log_callback(f"🛡️  Anti-Repeat History updated    : {history.path} ({len(history.entries)} tracked)")

        return {
            "count": len(prompts),
            "provider": provider_used,
            "target_window": window_label,
            "txt_path": txt_path,
            "json_path": json_path,
            "history_path": history.path,
            "history_count": len(history.entries),
            "prompts": prompts,
        }

    @staticmethod
    def _write_copy_paste_txt(
        txt_path: Path,
        prompts: List[Dict[str, str]],
        window_label: str,
        horizon_min: int,
        horizon_max: int,
        history_count: int,
        retention_days: int,
        provider: str,
        niche_focus: Optional[str],
    ):
        scenes = [p for p in prompts if p["asset_type"] == "scene"]
        isolated = [p for p in prompts if p["asset_type"] == "isolated"]

        lines = [
            "======================================================================",
            " HIGH-DEMAND COMMERCIAL MICROSTOCK PROMPT PACK (ADOBE STOCK READY)",
            f" Generated     : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f" Buyer Window  : {window_label} (H-{horizon_min} to H-{horizon_max} | 3-4 Months Ahead)",
            f" Anti-Repeat   : {history_count} unique subjects tracked ({retention_days}-day rolling memory)",
            f" Engine        : {provider}",
            f" Niche Focus   : {niche_focus or 'Auto (3-4 Month Seasonal + Daily Evergreen Rotation)'}",
            "======================================================================",
            "",
            "HOW TO USE (HYBRID WORKFLOW):",
            " 1. Copy the PROMPT below into your image generator (Firefly / Flux / Midjourney / Ideogram).",
            " 2. If your generator supports Negative Prompt / Exclude / --no, paste NEGATIVE PROMPT too.",
            " 3. Match the recommended Aspect Ratio (3:2 for Scenes, 1:1 for Isolated PNGs).",
            " 4. Save generated images into: ~/Desktop/microstock_generator/<folder_slug>/raw/",
            " 5. Run Step 4 pipeline: Run_Microstock_Generator.command (Vision QC + SEO + Upscale + CSV)",
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
                    f"Subject       : {p.get('subject', p['theme'])}",
                    f"Target Buyer  : {p['buyer']}",
                    f"Batch Folder  : {p['folder_slug']}/raw/",
                    f"Suggested File: {p.get('suggested_filename', '')}  (<= 30 chars, Adobe Stock ready)",
                    f"Aspect Ratio  : {p['aspect_ratio']}",
                    "PROMPT (COPY BELOW):",
                    p["prompt"],
                    f"NEGATIVE PROMPT (Optional): {p.get('negative_prompt', NEGATIVE_PROMPT_SCENE)}",
                    "----------------------------------------------------------------------",
                    "",
                ])

        if isolated:
            lines.append("######################################################################")
            lines.append(f" PART B: EDGE-SAFE ISOLATED TRANSPARENT PNGs ({len(isolated)} Prompts | Aspect Ratio 1:1)")
            lines.append(" TIP: Solid opaque high-contrast subjects on #FFFFFF with f/11 sharp focus")
            lines.append("      minimize halos, soft edges, and pixel gaps on Adobe Stock.")
            lines.append("######################################################################")
            lines.append("")
            for i, p in enumerate(isolated, start=1):
                lines.extend([
                    f"[{i:02d}] {p['theme']}",
                    f"Subject       : {p.get('subject', p['theme'])}",
                    f"Target Buyer  : {p['buyer']}",
                    f"Batch Folder  : {p['folder_slug']}/raw/",
                    f"Suggested File: {p.get('suggested_filename', '')}  (<= 30 chars, Adobe Stock ready)",
                    f"Aspect Ratio  : {p['aspect_ratio']}",
                    "PROMPT (COPY BELOW):",
                    p["prompt"],
                    f"NEGATIVE PROMPT (Optional): {p.get('negative_prompt', NEGATIVE_PROMPT_ISOLATED)}",
                    "----------------------------------------------------------------------",
                    "",
                ])

        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
