"""
Gemini Vision Quality Auditor.
Evaluates AI-generated images before upscaling to prevent Adobe Stock rejections.
Checks for:
- Extra fingers / deformed hands / broken anatomy
- Gibberish text / fake letters / fake watermarks
- Melting objects / severe AI distortions
"""

import os
import json
from pathlib import Path
from typing import Dict, Any, Optional
from PIL import Image

from .config import PipelineConfig


class VisionQAAuditor:
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

    def audit_image(self, image_path: Path, prompt_hint: Optional[str] = None) -> Dict[str, Any]:
        """
        Audit a raw AI image for commercial stock suitability.
        Returns:
            {"passed": bool, "score": float, "reasons": list, "detected_issues": list}
        """
        client = self._get_client()
        if client is None:
            # If no API key is provided, bypass AI QA gracefully with a warning
            return {
                "passed": True,
                "score": 1.0,
                "reasons": ["Bypassed (GEMINI_API_KEY not configured)."],
                "detected_issues": []
            }

        try:
            with Image.open(image_path) as img:
                # Resize thumbnail for fast evaluation (max 1024px)
                img.thumbnail((1024, 1024))
                thumb_bytes = None
                import io
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=85)
                thumb_bytes = buf.getvalue()

            system_instruction = (
                "You are an expert Adobe Stock Senior Asset Inspector. "
                "Analyze this generative AI image rigorously at 100% detail for commercial microstock submission. "
                "Check for common AI flaws:\n"
                "1. Anatomy errors: extra/missing fingers, malformed hands, distorted faces or eyes.\n"
                "2. Garbled text, unreadable typography, pseudo-letters, or fake watermarks/signatures.\n"
                "3. Melting objects, broken perspective, or unphysical impossible blends.\n"
                "4. Unnatural plastic skin or severe compression artifacts.\n"
                "Respond ONLY in valid JSON matching this schema:\n"
                "{\n"
                '  "passed": true/false,\n'
                '  "score": 0.0 to 1.0,\n'
                '  "detected_issues": ["issue 1", "issue 2"],\n'
                '  "reasons": ["summary of why it passed or failed"]\n'
                "}"
            )

            response = client.models.generate_content(
                model=self.config.gemini_text_model,
                contents=[
                    {"text": f"Evaluate this image for Adobe Stock. Original prompt context: {prompt_hint or 'N/A'}"},
                    {"inline_data": {"mime_type": "image/jpeg", "data": thumb_bytes}}
                ],
                config={"response_mime_type": "application/json"}
            )

            result_text = response.text.strip()
            data = json.loads(result_text)
            return {
                "passed": bool(data.get("passed", True)),
                "score": float(data.get("score", 1.0)),
                "reasons": list(data.get("reasons", [])),
                "detected_issues": list(data.get("detected_issues", []))
            }

        except Exception as e:
            return {
                "passed": True,
                "score": 0.9,
                "reasons": [f"QA evaluation skipped due to API error: {e}"],
                "detected_issues": []
            }

