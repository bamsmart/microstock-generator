"""
AI Image Generation Engine via Google GenAI / Imagen.
Includes prompt compliance guardrails and formatting for stock asset generation.
"""

import os
import io
import time
from pathlib import Path
from typing import List, Dict, Any, Tuple
from PIL import Image

from .config import PipelineConfig
from .compliance import sanitize_filename, FORBIDDEN_KEYWORDS


class GenerationEngine:
    def __init__(self, config: PipelineConfig):
        self.config = config
        self.api_key = os.getenv("GEMINI_API_KEY")
        self._client = None

    def _get_client(self):
        if self._client is None and self.api_key:
            try:
                from google import genai
                self._client = genai.Client(api_key=self.api_key)
            except Exception as e:
                print(f"⚠️ Could not initialize google-genai client: {e}")
        return self._client

    def prepare_prompt(self, user_prompt: str, asset_type: str = "isolated") -> str:
        """
        Enhance and guardrail user prompt for optimal Adobe Stock quality.
        """
        # 1. Clean forbidden terms
        clean_prompt = user_prompt.strip()
        lower_p = clean_prompt.lower()
        for forbidden in FORBIDDEN_KEYWORDS:
            if forbidden in lower_p:
                import re
                clean_prompt = re.sub(re.escape(forbidden), "", clean_prompt, flags=re.IGNORECASE).strip()

        # 2. Add stock-specific guidance
        if asset_type == "isolated":
            suffix = (
                ", isolated on pure solid white background, centered subject filling 75% to 85% of frame, "
                "clean distinct edges, soft even lighting, no drop shadows, no text, no watermark, no logo"
            )
        else:
            suffix = (
                ", commercial stock photograph, rich textures, balanced composition with subtle negative copy space, "
                "sharp professional focus, natural color grading, authentic lighting, no text, no watermark, no logo"
            )

        return f"{clean_prompt}{suffix}"

    def generate_batch(
        self,
        base_prompt: str,
        output_folder: Path,
        asset_type: str = "isolated",
        count: int = 4,
        batch_prefix: str = "asset",
        log_callback=print
    ) -> List[Tuple[Path, str]]:
        """
        Generate a batch of images using Imagen 3 / Gemini.
        Returns list of tuples: [(saved_image_path, effective_prompt), ...]
        """
        client = self._get_client()
        if client is None:
            raise RuntimeError(
                "GEMINI_API_KEY is not set in environment or .env file. "
                "Please add your GEMINI_API_KEY to proceed with AI generation."
            )

        output_folder.mkdir(parents=True, exist_ok=True)
        effective_prompt = self.prepare_prompt(base_prompt, asset_type=asset_type)
        aspect_ratio = self.config.aspect_ratio_isolated if asset_type == "isolated" else self.config.aspect_ratio_scene

        log_callback(f"\n🎨 Starting Generation: {count} image(s)")
        log_callback(f"   Asset Type: {asset_type.upper()} | Model: {self.config.gen_model} | Aspect Ratio: {aspect_ratio}")
        log_callback(f"   Prompt: {effective_prompt[:100]}...")

        results: List[Tuple[Path, str]] = []

        try:
            # Generate images via Google GenAI SDK
            # Using Imagen 3 format
            result = client.models.generate_images(
                model=self.config.gen_model,
                prompt=effective_prompt,
                config=dict(
                    number_of_images=min(count, 4),
                    output_mime_type="image/jpeg",
                    aspect_ratio=aspect_ratio,
                    person_generation="ALLOW_ADULT",
                    safety_filter_level="BLOCK_MEDIUM_AND_ABOVE"
                )
            )

            for idx, generated_img in enumerate(result.generated_images, start=1):
                raw_bytes = generated_img.image.image_bytes
                pil_img = Image.open(io.BytesIO(raw_bytes))

                # Sanitize filename (strictly <= 30 chars)
                filename = sanitize_filename(f"{batch_prefix}_{idx:02d}", ext=".jpg", max_len=self.config.max_filename_chars)
                save_path = output_folder / filename

                pil_img.save(save_path, format="JPEG", quality=95)
                results.append((save_path, effective_prompt))
                log_callback(f"  [Generated {idx}/{len(result.generated_images)}] Saved to {save_path.name} ✅")

        except Exception as e:
            log_callback(f"❌ Error during image generation: {e}")
            raise e

        return results

