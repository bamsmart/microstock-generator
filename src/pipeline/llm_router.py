"""
100% Free-Tier Cloud LLM & Vision Router with Automatic Fallback.
Zero paid APIs, zero Ollama dependency.

Text Chain (Research & Prompt Engineering):
  1. Groq Free Tier (openai/gpt-oss-120b -> fallback openai/gpt-oss-20b)
  2. Google AI Studio Gemini Free Tier (gemini-3.8-flash)
  3. Mistral AI Experiment Free Tier (mistral-small-latest)
  4. OpenRouter Free Auto-Router (openrouter/free)

Vision Chain (Step 4 QC + Adobe Stock SEO Metadata in 1 single API call):
  1. Google AI Studio Gemini Free Tier (gemini-3.8-flash, with 1 retry on transient 503)
  2. Mistral AI Experiment Free Tier (mistral-small-latest, native multimodal vision)
  3. OpenRouter Free Auto-Router (openrouter/free — auto-selects active free vision model)
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
        groq_model: str = "openai/gpt-oss-120b",
        mistral_model: str = "mistral-small-latest",
        openrouter_text_model: str = "openrouter/free",
        openrouter_vision_model: str = "openrouter/free",
        min_delay_sec: float = 4.5,
        timeout_sec: int = 25,
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
        # Circuit breaker: permanent disables vs transient 60s half-open cooldown
        self._disabled_providers: Dict[str, str] = {}
        self._cooldown_until: Dict[str, float] = {}
        self._consecutive_failures: Dict[str, int] = {}
        self.transient_cooldown_sec: float = 60.0

    def _is_permanent_or_quota_error(self, err_msg: str) -> bool:
        low = err_msg.lower()
        triggers = (
            "404", "not_found", "model_decommissioned", "model_not_found",
            "401", "403", "api_key_invalid", "invalid api key", "unauthorized",
            "resource_exhausted", "daily limit", "quota",
        )
        return any(t in low for t in triggers)

    def _is_provider_available(self, provider: str) -> bool:
        if provider in self._disabled_providers:
            return False
        until = self._cooldown_until.get(provider)
        if until is not None:
            if time.monotonic() < until:
                return False
            # Half-open cooldown expired -> allow provider to recover
            self._cooldown_until.pop(provider, None)
            self._consecutive_failures[provider] = 0
        return True

    def _record_success(self, provider: str):
        self._consecutive_failures[provider] = 0
        self._cooldown_until.pop(provider, None)

    def _record_failure(self, provider: str, err_msg: str, log_callback=None):
        low = err_msg.lower()
        # Transient 503 / high-demand spikes shouldn't immediately kill a healthy provider
        is_transient_503 = "503" in low or "unavailable" in low or "high demand" in low
        count = self._consecutive_failures.get(provider, 0) + 1
        self._consecutive_failures[provider] = count
        if self._is_permanent_or_quota_error(err_msg):
            self._disabled_providers[provider] = "quota/auth/model error"
            if log_callback:
                log_callback(f"     ⚡ Circuit breaker: disabling '{provider}' for rest of run (quota/auth/model error).")
            return
        threshold = 4 if is_transient_503 else 2
        if count >= threshold:
            self._cooldown_until[provider] = time.monotonic() + self.transient_cooldown_sec
            if log_callback:
                log_callback(
                    f"     ⚡ Circuit breaker: cooling down '{provider}' for {int(self.transient_cooldown_sec)}s "
                    f"({count} consecutive transient errors)."
                )

    def available_text_providers(self) -> List[str]:
        providers: List[str] = []
        if self.groq_key and self._is_provider_available("groq"):
            providers.append("groq")
        if self.gemini_key and self._is_provider_available("gemini"):
            providers.append("gemini")
        if self.mistral_key and self._is_provider_available("mistral"):
            providers.append("mistral")
        if self.openrouter_key and self._is_provider_available("openrouter"):
            providers.append("openrouter")
        return providers

    def available_vision_providers(self) -> List[str]:
        providers: List[str] = []
        if self.gemini_key and self._is_provider_available("gemini"):
            providers.append("gemini")
        if self.mistral_key and self._is_provider_available("mistral"):
            providers.append("mistral")
        if self.openrouter_key and self._is_provider_available("openrouter"):
            providers.append("openrouter")
        return providers

    def _throttle(self, log_callback=None):
        """Enforce gentle RPM spacing so free-tier quotas stay healthy."""
        if self.min_delay_sec <= 0:
            return
        now = time.monotonic()
        elapsed = now - self._last_call_ts
        if self._last_call_ts > 0 and elapsed < self.min_delay_sec:
            wait = self.min_delay_sec - elapsed
            if log_callback and wait >= 0.5:
                log_callback(f"     ⏳ Rate-limit spacing ({wait:.1f}s)...")
            time.sleep(wait)
        self._last_call_ts = time.monotonic()

    def _http_post_json(
        self,
        url: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ) -> Dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec, context=self._ssl_ctx) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="ignore")[:300]
            except Exception:
                pass
            detail = f"{e} | {err_body}" if err_body else str(e)
            raise RuntimeError(redact_secrets(detail)) from None

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

            client = genai.Client(
                api_key=self.gemini_key,
                http_options=types.HttpOptions(timeout=int(self.timeout_sec * 1000)),
            )
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
            self._throttle(log_callback=log_callback)
            t0 = time.monotonic()
            model_label = {
                "groq": self.groq_model,
                "gemini": self.gemini_model,
                "mistral": self.mistral_model,
                "openrouter": self.openrouter_text_model,
            }.get(provider, provider)
            if log_callback:
                log_callback(f"     ↳ Calling '{provider}' (model={model_label}, timeout={self.timeout_sec}s)...")
            try:
                if provider == "groq":
                    groq_candidates = [self.groq_model]
                    for alt in ("openai/gpt-oss-120b", "openai/gpt-oss-20b"):
                        if alt not in groq_candidates:
                            groq_candidates.append(alt)
                    raw = None
                    last_groq_err = None
                    for gm in groq_candidates:
                        try:
                            raw = self._call_openai_compat(
                                "https://api.groq.com/openai/v1/chat/completions",
                                self.groq_key,
                                gm,
                                system_prompt,
                                user_prompt,
                                expect_json=True,
                            )
                            break
                        except Exception as ge:
                            last_groq_err = ge
                            if "404" in str(ge) or "model_decommissioned" in str(ge) or "model_not_found" in str(ge):
                                continue
                            raise
                    if raw is None:
                        raise last_groq_err or RuntimeError("Groq models unavailable")
                elif provider == "gemini":
                    try:
                        raw = self._call_gemini(
                            system_prompt=system_prompt,
                            user_text=user_prompt,
                            image_bytes=None,
                            expect_json=True,
                        )
                    except Exception as ge:
                        if "503" in str(ge) or "UNAVAILABLE" in str(ge):
                            if log_callback:
                                log_callback("     ⏳ Gemini text 503 spike — retrying once in 4s...")
                            time.sleep(4.0)
                            raw = self._call_gemini(
                                system_prompt=system_prompt,
                                user_text=user_prompt,
                                image_bytes=None,
                                expect_json=True,
                            )
                        else:
                            raise
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

                try:
                    parsed = json.loads(_extract_json_block(raw))
                except json.JSONDecodeError as je:
                    if log_callback:
                        log_callback(f"     ⚠️ '{provider}' returned invalid JSON ({je}). Trying next fallback without disabling provider...")
                    continue
                self._record_success(provider)
                if log_callback:
                    log_callback(f"     ↳ Response from '{provider}' in {time.monotonic() - t0:.1f}s ✅")
                return parsed, provider

            except Exception as e:
                err_safe = redact_secrets(str(e))
                if log_callback:
                    log_callback(f"     ⚠️ '{provider}' failed after {time.monotonic() - t0:.1f}s ({err_safe}). Trying next fallback...")
                self._record_failure(provider, err_safe, log_callback=log_callback)
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
            self._throttle(log_callback=log_callback)
            t0 = time.monotonic()
            model_label = {
                "gemini": self.gemini_model,
                "mistral": self.mistral_model,
                "openrouter": self.openrouter_vision_model,
            }.get(provider, provider)
            if log_callback:
                log_callback(f"     ↳ Calling vision '{provider}' (model={model_label}, timeout={self.timeout_sec}s)...")
            try:
                if provider == "gemini":
                    try:
                        raw = self._call_gemini(
                            system_prompt=system_prompt,
                            user_text=user_prompt,
                            image_bytes=image_bytes,
                            mime_type=mime_type,
                            expect_json=True,
                        )
                    except Exception as ge:
                        if "503" in str(ge) or "UNAVAILABLE" in str(ge):
                            if log_callback:
                                log_callback("     ⏳ Gemini 503 high-demand spike — retrying once in 4s...")
                            time.sleep(4.0)
                            raw = self._call_gemini(
                                system_prompt=system_prompt,
                                user_text=user_prompt,
                                image_bytes=image_bytes,
                                mime_type=mime_type,
                                expect_json=True,
                            )
                        else:
                            raise
                elif provider == "mistral":
                    b64 = base64.b64encode(image_bytes).decode("ascii")
                    user_content = [
                        {"type": "text", "text": user_prompt},
                        {"type": "image_url", "image_url": f"data:{mime_type};base64,{b64}"},
                    ]
                    raw = self._call_openai_compat(
                        "https://api.mistral.ai/v1/chat/completions",
                        self.mistral_key,
                        self.mistral_model,
                        system_prompt,
                        user_content,
                        expect_json=True,
                    )
                elif provider == "openrouter":
                    b64 = base64.b64encode(image_bytes).decode("ascii")
                    user_content = [
                        {"type": "text", "text": user_prompt},
                        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64}"}},
                    ]
                    or_candidates = [self.openrouter_vision_model]
                    for alt in ("openrouter/free", "nvidia/nemotron-nano-12b-v2-vl:free", "google/gemma-4-31b-it:free"):
                        if alt not in or_candidates:
                            or_candidates.append(alt)
                    raw = None
                    last_or_err = None
                    for om in or_candidates:
                        try:
                            raw = self._call_openai_compat(
                                "https://openrouter.ai/api/v1/chat/completions",
                                self.openrouter_key,
                                om,
                                system_prompt,
                                user_content,
                                expect_json=False,
                                extra_headers={"HTTP-Referer": "https://localhost", "X-Title": "MicrostockGenerator"},
                            )
                            break
                        except Exception as oe:
                            last_or_err = oe
                            if "404" in str(oe) or "unavailable for free" in str(oe).lower():
                                continue
                            raise
                    if raw is None:
                        raise last_or_err or RuntimeError("OpenRouter free vision models unavailable")
                else:
                    continue

                try:
                    parsed = json.loads(_extract_json_block(raw))
                except json.JSONDecodeError as je:
                    if log_callback:
                        log_callback(f"     ⚠️ Vision '{provider}' returned invalid JSON ({je}). Trying next fallback without disabling provider...")
                    continue
                self._record_success(provider)
                if log_callback:
                    log_callback(f"     ↳ Vision response from '{provider}' in {time.monotonic() - t0:.1f}s ✅")
                return parsed, provider

            except Exception as e:
                err_safe = redact_secrets(str(e))
                if log_callback:
                    log_callback(f"     ⚠️ Vision '{provider}' failed after {time.monotonic() - t0:.1f}s ({err_safe}). Trying next fallback...")
                self._record_failure(provider, err_safe, log_callback=log_callback)
                continue

        return None, "all_failed"
