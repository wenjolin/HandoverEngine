"""Smoke tests for local BGE embedding backend (skipped if deps missing)."""

from __future__ import annotations

import pytest

from app.services.indexing.chroma_store import ChromaStore

pytest.importorskip("sentence_transformers")


def test_local_bge_embed_and_query(tmp_path):
    store = ChromaStore(
        tmp_path / "idx",
        embedding_backend="local",
        embedding_model="BAAI/bge-small-zh-v1.5",
    )
    store.add_chunks(
        [
            {
                "id": "1",
                "path": "README.md",
                "start_line": 1,
                "end_line": 2,
                "text": "如何用 docker compose 啟動專案",
            },
            {
                "id": "2",
                "path": "x.py",
                "start_line": 1,
                "end_line": 1,
                "text": "print('unrelated math formula xyz')",
            },
        ]
    )
    hits = store.query("docker compose 啟動", k=1)
    assert hits
    assert hits[0]["path"] == "README.md"
    assert len(hits[0]["text"]) > 0
