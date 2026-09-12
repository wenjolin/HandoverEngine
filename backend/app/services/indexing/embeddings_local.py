"""Local sentence-transformers embeddings (lazy-loaded).

Heavy dependency is imported only when EMBEDDING_BACKEND=local.
"""

from __future__ import annotations

from typing import Any

_model: Any = None
_model_name: str | None = None

_BATCH = 64


def embed_local(texts: list[str], model_name: str) -> list[list[float]]:
    """Encode texts with a local SentenceTransformer; L2-normalized."""
    global _model, _model_name
    if not texts:
        return []
    if _model is None or _model_name != model_name:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise ImportError(
                "本機 embedding 需要 sentence-transformers。"
                '請在 backend/.venv 執行: pip install -e ".[embed]"'
            ) from exc
        _model = SentenceTransformer(model_name)
        _model_name = model_name

    out: list[list[float]] = []
    for i in range(0, len(texts), _BATCH):
        batch = texts[i : i + _BATCH]
        vectors = _model.encode(
            batch,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        out.extend(v.tolist() for v in vectors)
    return out
