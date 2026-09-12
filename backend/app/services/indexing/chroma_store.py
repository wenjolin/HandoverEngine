"""Per-job vector store with fake, local (BGE), or OpenAI embeddings."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Sequence

from openai import OpenAI

from app.services.indexing.embeddings_local import embed_local

_VALID_BACKENDS = frozenset({"fake", "local", "openai"})


def _fake_embed(text: str, dim: int = 64) -> list[float]:
    """Deterministic embedding: same text → same vector (no network)."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    vals: list[float] = []
    seed = digest
    while len(vals) < dim:
        for b in seed:
            vals.append((b / 255.0) * 2 - 1)
            if len(vals) >= dim:
                break
        seed = hashlib.sha256(seed).digest()
    norm = math.sqrt(sum(v * v for v in vals)) or 1.0
    return [v / norm for v in vals]


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


class ChromaStore:
    """Lightweight persistent chunk store (JSON under persist_dir)."""

    def __init__(
        self,
        persist_dir: Path,
        *,
        embedding_backend: str = "fake",
        openai_api_key: str | None = None,
        openai_base_url: str | None = None,
        embedding_model: str = "BAAI/bge-small-zh-v1.5",
    ) -> None:
        backend = (embedding_backend or "fake").strip().lower()
        if backend not in _VALID_BACKENDS:
            raise ValueError(
                f"未知 embedding_backend={embedding_backend!r}，"
                f"請用 fake / local / openai"
            )
        if backend == "openai" and not openai_api_key:
            backend = "fake"

        self.persist_dir = persist_dir
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.embedding_backend = backend
        self.openai_api_key = openai_api_key
        self.openai_base_url = openai_base_url
        self.embedding_model = embedding_model
        self._path = self.persist_dir / "chunks.json"
        self._chunks: list[dict] = []
        if self._path.exists():
            self._chunks = json.loads(self._path.read_text(encoding="utf-8"))

    def _embed_many(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self.embedding_backend == "fake":
            return [_fake_embed(t) for t in texts]
        if self.embedding_backend == "local":
            return embed_local(texts, self.embedding_model)
        client = OpenAI(api_key=self.openai_api_key, base_url=self.openai_base_url)
        resp = client.embeddings.create(model=self.embedding_model, input=texts)
        data = sorted(resp.data, key=lambda d: d.index)
        return [list(d.embedding) for d in data]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return self._embed_many(texts)

    def iter_chunks(self) -> list[dict]:
        """Return stored chunk rows (without requiring private access)."""
        return list(self._chunks)

    def add_chunks(self, chunks: list[dict]) -> int:
        if not chunks:
            return 0
        vectors = self._embed_many([c["text"] for c in chunks])
        for chunk, vec in zip(chunks, vectors, strict=True):
            row = {**chunk, "embedding": vec}
            self._chunks.append(row)
        self._path.write_text(
            json.dumps(self._chunks, ensure_ascii=False),
            encoding="utf-8",
        )
        return len(chunks)

    def query(self, text: str, k: int = 8) -> list[dict]:
        if not self._chunks:
            return []
        q = self._embed_many([text])[0]
        scored = []
        for row in self._chunks:
            score = cosine_similarity(q, row["embedding"])
            scored.append((score, row))
        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for score, row in scored[:k]:
            results.append(
                {
                    "id": row["id"],
                    "path": row["path"],
                    "start_line": row["start_line"],
                    "end_line": row["end_line"],
                    "text": row["text"],
                    "score": score,
                }
            )
        return results
