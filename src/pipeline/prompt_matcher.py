"""
Step-1 Prompt Pack Filename Matcher.
Matches processed raw assets (including random/default LLM download names like
Gemini_Generated_Image_*.png) to saved prompts_*.json entries and applies the
prompt's descriptive Suggested File stem while strictly preserving result file type.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from .prompt_history import content_tokens

_GENERIC_ASSET_NOISE = frozenset({
    "white", "background", "backdrop", "studio", "isolated", "cutout", "transparent",
    "photo", "photograph", "image", "picture", "scene", "commercial", "stock",
    "macro", "lighting", "softbox", "clean", "minimalist", "minimal", "modern",
    "high", "resolution", "editorial", "concept", "design", "style", "texture",
    "gemini", "generated", "download", "chatgpt", "dalle", "midjourney", "firefly",
    "whisk", "imagen", "flux", "ideogram", "untitled", "export", "final", "img",
})


def _meaningful_tokens(text: str) -> Set[str]:
    return {t for t in content_tokens(text) if t not in _GENERIC_ASSET_NOISE}


def load_recent_prompt_entries(
    search_dirs: List[Path],
    max_files: int = 25,
) -> List[Dict[str, Any]]:
    """
    Load recent Step-1 prompt pack JSON entries from candidate prompt directories.
    Newest prompt packs appear first; safely ignores unreadable/sandboxed paths.
    """
    json_files: List[Path] = []
    seen_dirs: Set[Path] = set()
    for d in search_dirs:
        if d is None:
            continue
        try:
            resolved = d.resolve()
            if resolved in seen_dirs or not resolved.is_dir():
                continue
            seen_dirs.add(resolved)
            for p in resolved.glob("prompts_*.json"):
                if p.is_file():
                    json_files.append(p)
        except (PermissionError, OSError):
            continue

    # Newest filename timestamp first
    json_files.sort(key=lambda p: p.name, reverse=True)

    entries: List[Dict[str, Any]] = []
    seen_keys: Set[Tuple[str, str]] = set()
    for jf in json_files[:max_files]:
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
            for item in data.get("prompts", []):
                if not isinstance(item, dict):
                    continue
                sugg = str(item.get("suggested_filename", "")).strip()
                subj = str(item.get("subject", "")).strip()
                if not sugg:
                    continue
                key = (sugg.lower(), subj.lower())
                if key not in seen_keys:
                    seen_keys.add(key)
                    entries.append(item)
        except Exception:
            continue
    return entries


def match_prompt_filename_stem(
    title: str,
    keywords: List[str],
    orig_stem: str,
    folder_name: str,
    asset_type: str,
    prompt_entries: List[Dict[str, Any]],
    vision_slug: str = "",
) -> Optional[Tuple[str, Dict[str, Any], float]]:
    """
    Find the best-matching Step-1 prompt entry for a processed asset.
    Returns (suggested_stem, matched_entry, confidence_score) or None.
    Never modifies asset_type / output extension — callers keep their own extension.
    """
    if not prompt_entries:
        return None

    kw_head = " ".join(str(k) for k in (keywords or [])[:15])
    asset_tokens = _meaningful_tokens(f"{title} {kw_head} {vision_slug} {orig_stem}")
    folder_low = (folder_name or "").strip().lower()

    best_entry: Optional[Dict[str, Any]] = None
    best_score: float = 0.0
    best_overlap: int = 0
    best_folder_match: bool = False

    for entry in prompt_entries:
        sugg_name = str(entry.get("suggested_filename", "")).strip()
        if not sugg_name:
            continue
        stem = Path(sugg_name).stem.strip()
        if not stem:
            continue

        entry_folder = str(entry.get("folder_slug", "")).strip().lower()
        exact_folder = bool(folder_low and entry_folder and folder_low == entry_folder)

        prompt_text = f"{entry.get('subject', '')} {entry.get('theme', '')} {entry.get('folder_slug', '')}"
        prompt_tokens = _meaningful_tokens(prompt_text)
        stem_tokens = _meaningful_tokens(stem)
        all_prompt_tokens = prompt_tokens | stem_tokens

        overlap = len(asset_tokens & all_prompt_tokens)
        subj_recall = (len(asset_tokens & prompt_tokens) / float(len(prompt_tokens))) if prompt_tokens else 0.0
        stem_recall = (len(asset_tokens & stem_tokens) / float(len(stem_tokens))) if stem_tokens else 0.0
        type_bonus = 0.08 if str(entry.get("asset_type", "")).lower() == asset_type.lower() else 0.0
        folder_bonus = 0.50 if exact_folder else 0.0

        score = (0.65 * subj_recall) + (0.35 * stem_recall) + type_bonus + folder_bonus

        if score > best_score:
            best_score = score
            best_entry = entry
            best_overlap = overlap
            best_folder_match = exact_folder

    if best_entry is None:
        return None

    # Guard against accidental false positives on unrelated ad-hoc images
    if best_folder_match and best_score >= 0.50:
        return Path(str(best_entry["suggested_filename"])).stem, best_entry, round(best_score, 3)

    if best_overlap >= 2 and best_score >= 0.38:
        return Path(str(best_entry["suggested_filename"])).stem, best_entry, round(best_score, 3)

    return None
