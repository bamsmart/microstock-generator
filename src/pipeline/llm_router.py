"""
100% Free-Tier Cloud LLM & Vision Router with Automatic Fallback.
Zero paid APIs, zero Ollama dependency.

Text Chain (Research & Prompt Engineering):
  1. Groq Free Tier (llama-3.3-70b-versatile)
  2. Google AI Studio Gemini Free Tier (gemini-2.5-flash)
  3. Mistral AI Experiment Free Tier (mistral-small-latest)
  4. OpenRouter :free (meta-llama/llama-3.3-70b-instruct:free)

Vision Chain (Step 4 QC + Adobe Stock SEO Metadata in 1 single API call):
  1. Google AI Studio Gemini Free Tier (gemini-2.5-flash)
  2. OpenRouter Vision :free (google/gemma-3-27b-it:free)
"""

import base64
import json
import os
import re
import ssl
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from .logger import redact_secrets


def build_ssl_context() -> ssl.SSLContext:
    """Create an SSLContext using certifi CA bundle (fixes macOS python.org SSL_VERIFY_FAILED)."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _extract_json_block(text: str) -> str:
    """Extract clean JSON from markdown code fences or raw LLM text."""
    cleaned = text.strip()
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned, flags=re.IGNORECASE)
    if fence_match:
        cleaned = fence_match.group(1).strip()
    # Find outermost JSON object or array
    start_obj = cleaned.find("{")
    start_arr = cleaned.find("[")
    starts = [i for i in (start_obj, start_arr) if i != -1]
    if not starts:
        return cleaned
    start = min(starts)
    open_ch = cleaned[start]
    close_ch = "}" if open_ch == "{" else "]"
    end = cleaned.rfind(close_ch)
    if end != -1 and end > start:
        return cleaned[start : end + 1]
    return cleaned


class FreeTierLLMRouter:
    """Routes text and vision requests across free-tier providers with rate-limit throttling."""

    def __init__(
        self,
        gemini_model: str = "gemini-3.8-flash",
        groq_model: str = "llama-3.3-70b-versatile",
        mistral_model: str = "mistral-small-latest",
        openrouter_text_model: str = "meta-llama/llama-3.3-70b-instruct:free",
        openrouter_vision_model: str = "google/gemma-3-27b-it:free",
        min_delay_sec: float = 4.5,
        timeout_sec: int = 45,
    ):
        self.gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
        self.groq_key = os.getenv("GROQ_API_KEY", "").strip()
        self.mistral_key = os.getenv("MISTRAL_API_KEY", "").strip()
        self.openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()

        self.gemini_model = gemini_model
        self.groq_model = groq_model
        self.mistral_model = mistral_model
        self.openrouter_text_model = openrouter_text_model
        self.openrouter_vision_model = openrouter_vision_model

        self.min_delay_sec = max(0.0, float(min_delay_sec))
        self.timeout_sec = timeout_sec
        self._last_call_ts: float = 0.0
        self._ssl_ctx = build_ssl_context()

    def available_text_providers(self) -> List[str]:
        providers: List[str] = []
        if self.groq_key:
            providers.append("groq")
        if self.gemini_key:
            providers.append("gemini")
        if self.mistral_key:
            providers.append("mistral")
        if self.openrouter_key:
            providers.append("openrouter")
        return providers

    def available_vision_providers(self) -> List[str]:
        providers: List[str] = []
        if self.gemini_key:
            providers.append("gemini")
        if self.openrouter_key:
            providers.append("openrouter")
        return providers

    def _throttle(self):
        """Enforce gentle RPM spacing so free-tier quotas stay healthy."""
        if self.min_delay_sec <= 0:
            return
        now = time.monotonic()
        elapsed = now - self._last_call_ts
        if self._last_call_ts > 0 and elapsed < self.min_delay_sec:
            time.sleep(self.min_delay_sec - elapsed)
        self._last_call_ts = time.monotonic()

    def _http_post_json(
        self,
        url: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ) -> Dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout_sec, context=self._ssl_ctx) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw)

    def _call_openai_compat(
        self,
        endpoint: str,
        api_key: str,
        model: str,
        system_prompt: str,
        user_content: Any,
        expect_json: bool = True,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> str:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "MicrostockGenerator/2.0",
        }
        if extra_headers:
            headers.update(extra_headers)

        payload: Dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.4,
        }
        if expect_json:
            payload["response_format"] = {"type": "json_object"}

        data = self._http_post_json(endpoint, payload, headers)
        return data["choices"][0]["message"]["content"]

    def _call_gemini(
        self,
        system_prompt: str,
        user_text: str,
        image_bytes: Optional[bytes] = None,
        mime_type: str = "image/jpeg",
        expect_json: bool = True,
    ) -> str:
        """Calls Gemini Free Tier via google-genai SDK (or REST fallback)."""
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=self.gemini_key)
            contents: List[Any] = [user_text]
            if image_bytes is not None:
                contents.append(types.Part.from_bytes(data=image_bytes, mime_type=mime_type))

            cfg_kwargs: Dict[str, Any] = {
                "system_instruction": system_prompt,
                "temperature": 0.4,
            }
            if expect_json:
                cfg_kwargs["response_mime_type"] = "application/json"

            response = client.models.generate_content(
                model=self.gemini_model,
                contents=contents,
                config=types.GenerateContentConfig(**cfg_kwargs),
            )
            return (response.text or "").strip()
        except ImportError:
            # Pure REST fallback if google-genai is not installed (key passed in header, never in URL)
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{self.gemini_model}:generateContent"
            )
            parts: List[Dict[str, Any]] = [{"text": user_text}]
            if image_bytes is not None:
                parts.append({
                    "inline_data": {
                        "mime_type": mime_type,
                        "data": base64.b64encode(image_bytes).decode("ascii"),
                    }
                })
            payload: Dict[str, Any] = {
                "system_instruction": {"parts": [{"text": system_prompt}]},
                "contents": [{"parts": parts}],
                "generationConfig": {"temperature": 0.4},
            }
            if expect_json:
                payload["generationConfig"]["responseMimeType"] = "application/json"

            data = self._http_post_json(
                url,
                payload,
                {
                    "Content-Type": "application/json",
                    "x-goog-api-key": self.gemini_key,
                },
            )
            return data["candidates"][0]["content"]["parts"][0]["text"]

    def generate_json_text(
        self,
        system_prompt: str,
        user_prompt: str,
        log_callback=None,
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        """
        Try free-tier text providers in priority order:
        Groq -> Gemini Flash -> Mistral -> OpenRouter :free.
        Returns (parsed_json_or_None, provider_name).
        """
        providers = self.available_text_providers()
        if not providers:
            return None, "offline_fallback"

        for provider in providers:
            self._throttle()
            try:
                if provider == "groq":
                    raw = self._call_openai_compat(
                        "https://api.groq.com/openai/v1/chat/completions",
                        self.groq_key,
                        self.groq_model,
                        system_prompt,
                        user_prompt,
                        expect_json=True,
                    )
                elif provider == "gemini":
                    raw = self._call_gemini(
                        system_prompt=system_prompt,
                        user_text=user_prompt,
                        image_bytes=None,
                        expect_json=True,
                    )
                elif provider == "mistral":
                    raw = self._call_openai_compat(
                        "https://api.mistral.ai/v1/chat/completions",
                        self.mistral_key,
                        self.mistral_model,
                        system_prompt,
                        user_prompt,
                        expect_json=True,
                    )
                elif provider == "openrouter":
                    raw = self._call_openai_compat(
                        "https://openrouter.ai/api/v1/chat/completions",
                        self.openrouter_key,
                        self.openrouter_text_model,
                        system_prompt,
                        user_prompt,
                        expect_json=True,
                        extra_headers={"HTTP-Referer": "https://localhost", "X-Title": "MicrostockGenerator"},
                    )
                else:
                    continue

                parsed = json.loads(_extract_json_block(raw))
                return parsed, provider

            except Exception as e:
                if log_callback:
                    log_callback(f"  ⚠️ Free-tier provider '{provider}' failed ({redact_secrets(str(e))}). Trying next fallback...")
                continue

        return None, "all_failed"

    def analyze_image_json(
        self,
        image_bytes: bytes,
        system_prompt: str,
        user_prompt: str,
        mime_type: str = "image/jpeg",
        log_callback=None,
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        """
        Try free-tier Vision providers in priority order:
        Gemini Flash Free -> OpenRouter Vision :free.
        Returns (parsed_json_or_None, provider_name).
        """
        providers = self.available_vision_providers()
        if not providers:
            return None, "offline_fallback"

        for provider in providers:
            self._throttle()
            try:
                if provider == "gemini":
                    raw = self._call_gemini(
                        system_prompt=system_prompt,
                        user_text=user_prompt,
                        image_bytes=image_bytes,
                        mime_type=mime_type,
                        expect_json=True,
                    )
                elif provider == "openrouter":
                    b64 = base64.b64encode(image_bytes).decode("ascii")
                    user_content = [
                        {"type": "text", "text": user_prompt},
                        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64}"}},
                    ]
                    raw = self._call_openai_compat(
                        "https://openrouter.ai/api/v1/chat/completions",
                        self.openrouter_key,
                        self.openrouter_vision_model,
                        system_prompt,
                        user_content,
                        expect_json=False,
                        extra_headers={"HTTP-Referer": "https://localhost", "X-Title": "MicrostockGenerator"},
                    )
                else:
                    continue

                parsed = json.loads(_extract_json_block(raw))
                return parsed, provider

            except Exception as e:
                if log_callback:
                    log_callback(f"  ⚠️ Free-tier vision provider '{provider}' failed ({redact_secrets(str(e))}). Trying next fallback...")
                continue

        return None, "all_failed"
