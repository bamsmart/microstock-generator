"""
Fase 4: Commercial-Safe (MIT) OpenCLIP Semantic Deduplication & Keyword Relevance Auditor.
- Detects cross-angle / slight-crop "Similar Content" duplicates that pHash alone misses.
- Scores Top-10 Adobe Stock keywords against the rendered image using zero-shot CLIP cosine similarity.
- 100% lazy-loaded and gracefully skips when disabled or when HuggingFace weights aren't cached offline.
"""

from pathlib import Path
from typing import List, Optional, Tuple
import numpy as np
from PIL import Image, ImageOps


class SemanticAuditor:
    """Lazy-loading OpenCLIP CPU auditor with zero-cost fallback when unavailable."""

    def __init__(
        self,
        model_name: str = "ViT-B-32",
        pretrained: str = "laion2b_s34b_b79k",
        enabled: bool = True,
    ):
        self.model_name = model_name
        self.pretrained = pretrained
        self.enabled = enabled
        self._model = None
        self._preprocess = None
        self._tokenizer = None
        self._load_failed_reason: Optional[str] = None

    @staticmethod
    def packages_installed() -> bool:
        try:
            import open_clip  # noqa: F401
            import torch  # noqa: F401
            return True
        except Exception:
            return False

    def _ensure_loaded(self) -> bool:
        if not self.enabled or self._load_failed_reason is not None:
            return False
        if self._model is not None:
            return True
        try:
            import open_clip
            model, _, preprocess = open_clip.create_model_and_transforms(
                self.model_name,
                pretrained=self.pretrained,
                device="cpu",
            )
            model.eval()
            self._model = model
            self._preprocess = preprocess
            self._tokenizer = open_clip.get_tokenizer(self.model_name)
            return True
        except Exception as e:
            self._load_failed_reason = str(e)
            return False

    @staticmethod
    def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
        a = np.asarray(vec_a, dtype=np.float32)
        b = np.asarray(vec_b, dtype=np.float32)
        na = float(np.linalg.norm(a))
        nb = float(np.linalg.norm(b))
        if na == 0.0 or nb == 0.0 or a.shape != b.shape:
            return 0.0
        return float(np.dot(a, b) / (na * nb))

    def embed_image(self, image_path: Path) -> Optional[List[float]]:
        """Compute L2-normalized CLIP embedding on CPU. Returns None if unavailable/offline."""
        if not self._ensure_loaded() or not image_path.exists():
            return None
        try:
            import torch
            with Image.open(image_path) as raw:
                im = ImageOps.exif_transpose(raw).convert("RGB")
                tensor = self._preprocess(im).unsqueeze(0)
            with torch.no_grad():
                feat = self._model.encode_image(tensor)
                feat = feat / feat.norm(dim=-1, keepdim=True)
                return [round(float(v), 5) for v in feat[0].cpu().numpy().tolist()]
        except Exception:
            return None

    def find_semantic_duplicate(
        self,
        embedding: Optional[List[float]],
        portfolio_entries: List[dict],
        threshold: float = 0.92,
        exclude_filename: Optional[str] = None,
    ) -> Optional[Tuple[dict, float]]:
        """Compare embedding against existing portfolio CLIP vectors."""
        if not embedding:
            return None
        best: Optional[Tuple[dict, float]] = None
        for entry in portfolio_entries:
            fn = entry.get("filename")
            if exclude_filename and fn == exclude_filename:
                continue
            other_vec = entry.get("clip_vec")
            if not other_vec:
                continue
            sim = self.cosine_similarity(embedding, other_vec)
            if sim >= threshold:
                if best is None or sim > best[1]:
                    best = (entry, round(sim, 3))
        return best

    def score_keywords_relevance(
        self,
        image_embedding: Optional[List[float]],
        keywords: List[str],
        top_k: int = 10,
    ) -> List[Tuple[str, float]]:
        """Score top-k Adobe Stock keywords against image embedding via zero-shot CLIP cosine."""
        if not image_embedding or not keywords or not self._ensure_loaded():
            return []
        subset = [k.strip() for k in keywords if k and k.strip()][:top_k]
        if not subset:
            return []
        try:
            import torch
            prompts = [f"commercial stock photo of {kw}" for kw in subset]
            tokens = self._tokenizer(prompts)
            with torch.no_grad():
                tfeat = self._model.encode_text(tokens)
                tfeat = tfeat / tfeat.norm(dim=-1, keepdim=True)
                img_np = np.asarray(image_embedding, dtype=np.float32)
                img_norm = float(np.linalg.norm(img_np)) or 1.0
                img_np = img_np / img_norm
                sims = (tfeat.cpu().numpy() @ img_np).tolist()
            return [(kw, round(float(s), 3)) for kw, s in zip(subset, sims)]
        except Exception:
            return []
