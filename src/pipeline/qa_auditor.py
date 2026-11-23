"""
Free-Tier Vision Quality Auditor & Adobe Stock SEO Metadata Engine (Step 4).

Combines AI Quality Inspection + Commercial SEO Metadata Generation in a SINGLE
Free-Tier Vision API call (saving 50% of daily free quota):
  Primary  : Google AI Studio Gemini Flash Free Tier
  Fallback : OpenRouter Vision (:free)
  Offline  : Graceful fallback to LocalMetadataEngine (no crash if no API key)

Checks for:
  - Extra fingers / deformed hands / distorted faces or eyes
  - Gibberish text / fake letters / accidental watermarks or logos
  - Melting objects / broken perspective / severe AI artifacts

Generates Adobe-compliant metadata:
  - Title (<= 70 chars, no commas, no AI buzzwords or brands)
  - 35-49 Keywords ordered by relevance (top 10 most important first)
  - Official Adobe Stock Category ID (1-21)
  - Clean SEO Filename slug (<= 30 chars)
"""

import io
from pathlib import Path
from typing import Any, Dict, Optional
from PIL import Image, ImageOps

from .categories import ADOBE_STOCK_CATEGORIES, normalize_category_id
from .compliance import GENERIC_FILLER_KEYWORDS, lint_keywords, lint_title, sanitize_filename
from .config import PipelineConfig
from .llm_router import FreeTierLLMRouter
from .local_metadata import LocalMetadataEngine


class VisionQAAuditor:
    def __init__(self, config: PipelineConfig, llm_router: Optional[FreeTierLLMRouter] = None):
        self.config = config
        self.llm = llm_router or FreeTierLLMRouter(
            gemini_model=config.gemini_text_model,
            groq_model=config.groq_model,
            mistral_model=config.mistral_model,
            openrouter_text_model=config.openrouter_text_model,
            openrouter_vision_model=config.openrouter_vision_model,
            min_delay_sec=config.free_tier_delay_sec,
        )

    @staticmethod
    def _prepare_thumbnail_bytes(image_path: Path, max_dim: int = 1024) -> bytes:
        with Image.open(image_path) as raw_img:
            img = ImageOps.exif_transpose(raw_img).convert("RGB")
            img.thumbnail((max_dim, max_dim))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            return buf.getvalue()

    def audit_and_generate_metadata(
        self,
        image_path: Path,
        asset_type: str = "scene",
        prompt_hint: Optional[str] = None,
        log_callback=None,
    ) -> Dict[str, Any]:
        """
        Single-call Free-Tier Vision QC + Adobe Stock SEO Metadata generator.
        Falls back gracefully to LocalMetadataEngine if no free-tier vision key is configured.
        """
        # Combine folder context + individual filename stem so offline fallback is specific per image
        folder_hint = prompt_hint or image_path.parent.name.replace("_result", "").replace("_upscaled", "")
        if folder_hint.lower() in ("raw", "result", "upscaled", "input", "microstock_generator", "microstock-generator", ""):
            folder_hint = ""
        file_hint = image_path.stem.replace("_", " ").replace("-", " ")
        theme_hint = f"{folder_hint} {file_hint}".strip() if folder_hint and folder_hint.lower() not in file_hint.lower() else (file_hint or folder_hint or "commercial stock")

        # If no Vision API key is set, bypass AI QC and fall back to offline metadata
        if not self.llm.available_vision_providers():
            cat_id, cat_name = LocalMetadataEngine.infer_category(theme_hint)
            title = LocalMetadataEngine.generate_title(
                theme_hint, asset_type=asset_type, max_chars=self.config.max_title_chars
            )
            keywords = LocalMetadataEngine.generate_keywords(
                theme_hint, asset_type=asset_type, max_count=self.config.max_keywords
            )
            out_ext = ".png" if asset_type == "isolated" else ".jpg"
            return {
                "passed": True,
                "score": 1.0,
                "detected_issues": [],
                "reasons": ["Vision AI bypassed (no GEMINI_API_KEY or OPENROUTER_API_KEY in .env)."],
                "title": title,
                "keywords": keywords,
                "category_id": cat_id,
                "category_name": cat_name,
                "suggested_filename": sanitize_filename(image_path.stem, ext=out_ext, max_len=self.config.max_filename_chars),
                "provider": "offline_local_metadata",
            }

        try:
            thumb_bytes = self._prepare_thumbnail_bytes(image_path)
        except Exception as e:
            return {
                "passed": False,
                "score": 0.0,
                "detected_issues": [f"Image read error: {e}"],
                "reasons": ["Could not open image for Vision QC."],
                "title": "",
                "keywords": [],
                "category_id": 8,
                "category_name": ADOBE_STOCK_CATEGORIES[8],
                "suggested_filename": image_path.name,
                "provider": "error",
            }

        categories_ref = ", ".join(f"{k}:{v}" for k, v in ADOBE_STOCK_CATEGORIES.items())

        system_prompt = (
            "You are a Top-1% Adobe Stock Microstock SEO Consultant AND Senior Asset Quality Inspector.\n"
            "Your metadata directly determines whether this asset ranks on Page 1 and earns commercial sales.\n"
            "Perform TWO tasks in ONE strict JSON response:\n\n"
            "TASK 1 — COMMERCIAL QUALITY AUDIT:\n"
            "Inspect the image at 100% detail for AI defects that cause Adobe Stock rejections:\n"
            "  - Anatomy flaws: extra/missing fingers, deformed hands, distorted eyes/faces.\n"
            "  - Garbled text, unreadable pseudo-letters, accidental logos, or watermarks.\n"
            "  - Melting objects, broken perspective, severe artifacts, or plastic distortion.\n"
            "Set 'passed': false if any clear commercial defect exists (score < 0.70).\n\n"
            "TASK 2 — ULTRA-SPECIFIC ADOBE STOCK SEO METADATA (describe ONLY what is visually present):\n"
            "  1. 'title' (max 70 chars, plain English phrase, NO commas, NO brand names, NO AI buzzwords):\n"
            "     Use the high-converting Adobe Stock formula:\n"
            "     [Specific Style/Material] + [Exact Main Subject] + [Key Visual Detail/Color] + [Setting/Copy Space or Isolated]\n"
            "     BAD (too generic): 'Modern office desk scene' or 'Floral watercolor graphic'\n"
            "     GOOD (specific): 'Sunlit oak desk with matte ceramic coffee mug and linen notebook'\n"
            "     GOOD (isolated): 'Hand painted watercolor pink peony and eucalyptus bouquet isolated'\n\n"
            "  2. 'keywords' (array of 35-45 hyper-specific lowercase English keywords, STRICTLY ORDERED by search weight):\n"
            "     - Slots #1 to #10 (CRITICAL — highest Adobe Stock algorithm weight):\n"
            "       Exact literal subject nouns, primary object, exact style/medium, and primary commercial concept.\n"
            "       NEVER put vague words in slots #1-#10.\n"
            "     - Slots #11 to #25 (Visual Specifics):\n"
            "       Exact colors (e.g. 'warm beige', 'sage green', 'champagne gold'), materials/textures\n"
            "       (e.g. 'travertine', 'brushed brass', 'raw linen', 'frosted glass'), lighting ('morning sunlight',\n"
            "       'soft shadow', 'studio lighting'), and camera/framing ('overhead', 'flatlay', 'copy space', 'isolated').\n"
            "     - Slots #26 to #45 (Buyer Intent & Commercial Use Cases):\n"
            "       Specific industries & design uses (e.g. 'skincare', 'packaging', 'hero banner', 'branding',\n"
            "       'wedding invitation', 'fintech', 'ramadan', 'wellness', 'e-commerce', 'product display').\n"
            "     - STRICTLY FORBIDDEN generic filler words: 'beautiful', 'nice', 'amazing', 'creative', 'artistic',\n"
            "       'visual', 'element', 'object', 'item', 'image', 'picture', 'high quality', 'high resolution',\n"
            "       'photorealistic', '8k', '4k', 'generative ai', 'midjourney'.\n\n"
            f"  3. 'category_id': Exact integer 1-21 from Adobe Stock taxonomy: {categories_ref}.\n"
            "  4. 'filename_slug': Specific descriptive snake_case slug of the main subject (max 22 chars, ASCII only).\n\n"
            "Respond ONLY in valid JSON with this exact schema:\n"
            "{\n"
            '  "passed": true,\n'
            '  "score": 0.92,\n'
            '  "detected_issues": [],\n'
            '  "reasons": ["Sharp commercial focus, natural lighting, clean copy space"],\n'
            '  "title": "Minimalist travertine stone podium with palm leaf shadow on beige wall",\n'
            '  "keywords": ["podium", "travertine", "product display", "cosmetic backdrop", "minimalist", ...],\n'
            '  "category_id": 8,\n'
            '  "filename_slug": "travertine_podium_beige"\n'
            "}"
        )

        user_prompt = (
            f"Asset type: {asset_type.upper()} "
            f"({'isolated cutout on white/transparent background' if asset_type == 'isolated' else 'full-scene photograph/backdrop'}). "
            f"Context hint: {theme_hint}. Evaluate quality and generate Adobe Stock SEO metadata."
        )

        data, provider = self.llm.analyze_image_json(
            image_bytes=thumb_bytes,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            mime_type="image/jpeg",
            log_callback=log_callback,
        )

        out_ext = ".png" if asset_type == "isolated" else ".jpg"

        if not data:
            # Graceful fallback if all free-tier providers hit rate limits
            cat_id, cat_name = LocalMetadataEngine.infer_category(theme_hint)
            title = LocalMetadataEngine.generate_title(
                theme_hint, asset_type=asset_type, max_chars=self.config.max_title_chars
            )
            keywords = LocalMetadataEngine.generate_keywords(
                theme_hint, asset_type=asset_type, max_count=self.config.max_keywords
            )
            return {
                "passed": True,
                "score": 0.85,
                "detected_issues": [],
                "reasons": [f"Vision API unavailable ({provider}); fell back to local metadata."],
                "title": title,
                "keywords": keywords,
                "category_id": cat_id,
                "category_name": cat_name,
                "suggested_filename": sanitize_filename(image_path.stem, ext=out_ext, max_len=self.config.max_filename_chars),
                "provider": f"fallback_local ({provider})",
            }

        # Lint & enforce Adobe Stock compliance rules on LLM output
        raw_title = str(data.get("title", "")).strip() or LocalMetadataEngine.generate_title(theme_hint, asset_type=asset_type)
        clean_title, _ = lint_title(raw_title, max_chars=self.config.max_title_chars)

        raw_kw = data.get("keywords", [])
        if isinstance(raw_kw, str):
            raw_kw = [k.strip() for k in raw_kw.split(",") if k.strip()]
        clean_kw, _ = lint_keywords(list(raw_kw), max_count=self.config.max_keywords)
        # Strip weak generic filler words so top Adobe Stock keyword slots stay razor-specific
        specific_kw = [k for k in clean_kw if k not in GENERIC_FILLER_KEYWORDS]
        if len(specific_kw) >= 15:
            clean_kw = specific_kw
        if len(clean_kw) < self.config.min_keywords:
            fallback_kw = LocalMetadataEngine.generate_keywords(
                clean_title or theme_hint, asset_type=asset_type, max_count=self.config.max_keywords
            )
            for k in fallback_kw:
                if k not in clean_kw and k not in GENERIC_FILLER_KEYWORDS and len(clean_kw) < self.config.max_keywords:
                    clean_kw.append(k)

        cat_id = normalize_category_id(data.get("category_id", 8))
        cat_name = ADOBE_STOCK_CATEGORIES[cat_id]

        raw_slug = str(data.get("filename_slug", "")).strip() or image_path.stem
        suggested_filename = sanitize_filename(raw_slug, ext=out_ext, max_len=self.config.max_filename_chars)

        score = float(data.get("score", 0.9))
        passed = bool(data.get("passed", score >= 0.70))

        return {
            "passed": passed,
            "score": round(score, 2),
            "detected_issues": list(data.get("detected_issues", [])),
            "reasons": list(data.get("reasons", [])),
            "title": clean_title,
            "keywords": clean_kw,
            "category_id": cat_id,
            "category_name": cat_name,
            "suggested_filename": suggested_filename,
            "provider": provider,
        }

    def audit_image(self, image_path: Path, prompt_hint: Optional[str] = None) -> Dict[str, Any]:
        """Backward-compatible wrapper returning QC fields."""
        res = self.audit_and_generate_metadata(image_path, asset_type="scene", prompt_hint=prompt_hint)
        return {
            "passed": res["passed"],
            "score": res["score"],
            "reasons": res["reasons"],
            "detected_issues": res["detected_issues"],
        }
