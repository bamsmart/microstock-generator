"""
Prompt History & Anti-Repeat Engine for Daily Step 1 Research.

Keeps a rolling log of every generated prompt (default: last 120 days) in
<prompts_dir>/prompt_history.json so daily runs never produce the same subject twice.

Duplicate detection:
  - Exact `variant_key` match (offline library combinations)
  - Fuzzy content similarity (Jaccard on subject-bearing words) >= threshold
"""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

# Boilerplate words injected by the commercial recipe — ignored for similarity scoring
_BOILERPLATE = {
    "isolated", "pure", "solid", "white", "background", "ffffff", "studio", "lighting", "light", "soft",
    "even", "crisp", "clean", "edges", "edge", "shadow", "shadows", "drop", "cast", "text", "logos",
    "logo", "watermark", "watermarks", "copy", "space", "negative", "natural", "frame", "centered",
    "filling", "margin", "sides", "subject", "silhouette", "uncropped", "full", "commercial",
    "photograph", "photography", "product", "editorial", "authentic", "textures", "texture", "sharp",
    "focus", "lens", "shot", "with", "from", "and", "the", "for", "into", "onto", "over", "under",
    "zero", "gradient", "vignette", "seamless", "noise", "free", "grain", "realistic", "color",
    "grading", "designer", "typography", "generous", "third", "left", "right", "upper", "view",
    "front", "angle", "degree", "softbox", "softboxes", "rim", "macro", "aperture", "detail",
    "highly", "professional", "catalog", "cutout", "high", "quality", "lit", "evenly", "fully",
}

_WORD_RE = re.compile(r"[a-z]{3,}")


def content_tokens(text: str) -> set:
    return {w for w in _WORD_RE.findall((text or "").lower()) if w not in _BOILERPLATE}


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class PromptHistory:
    def __init__(self, history_path: Path, retention_days: int = 120, similarity_threshold: float = 0.5):
        self.path = Path(history_path)
        self.retention_days = max(1, int(retention_days))
        self.threshold = float(similarity_threshold)
        self.entries: List[Dict[str, Any]] = self._load()
        self._prune()

    def _load(self) -> List[Dict[str, Any]]:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                return list(data.get("entries", []))
            except Exception:
                return []
        return []

    def _prune(self):
        cutoff = datetime.now() - timedelta(days=self.retention_days)
        kept = []
        for e in self.entries:
            try:
                if datetime.fromisoformat(e.get("date", "")) >= cutoff:
                    kept.append(e)
            except Exception:
                continue
        self.entries = kept

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        try:
            tmp.write_text(
                json.dumps({"retention_days": self.retention_days, "entries": self.entries}, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            tmp.replace(self.path)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink(missing_ok=True)
                except Exception:
                    pass

    def _signature_text(self, subject: str, theme: str, raw_prompt: str) -> str:
        head = " ".join((raw_prompt or "").split()[:22])
        return f"{subject} {theme} {head}"

    def is_duplicate(
        self,
        subject: str,
        theme: str,
        raw_prompt: str,
        asset_type: str,
        variant_key: Optional[str] = None,
        extra_pool: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        pool = list(self.entries) + list(extra_pool or [])
        sig = content_tokens(self._signature_text(subject, theme, raw_prompt))
        subj_tokens = content_tokens(subject)
        for e in pool:
            if variant_key and e.get("variant_key") == variant_key:
                return True
            if e.get("asset_type") != asset_type:
                continue
            if subj_tokens and subj_tokens == set(e.get("subject_tokens", [])):
                return True
            if jaccard(sig, set(e.get("sig_tokens", []))) >= self.threshold:
                return True
        return False

    def make_entry(
        self,
        subject: str,
        theme: str,
        raw_prompt: str,
        asset_type: str,
        variant_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        return {
            "date": datetime.now().isoformat(timespec="seconds"),
            "asset_type": asset_type,
            "subject": subject,
            "theme": theme,
            "variant_key": variant_key or "",
            "subject_tokens": sorted(content_tokens(subject)),
            "sig_tokens": sorted(content_tokens(self._signature_text(subject, theme, raw_prompt))),
        }

    def add(self, entry: Dict[str, Any]):
        self.entries.append(entry)

    def recent_subjects(self, limit: int = 60) -> List[str]:
        out: List[str] = []
        for e in reversed(self.entries):
            label = f"{e.get('asset_type', '')}: {e.get('subject') or e.get('theme', '')}".strip()
            if label not in out:
                out.append(label)
            if len(out) >= limit:
                break
        return out
