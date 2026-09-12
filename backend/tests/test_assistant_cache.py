"""Assistant query tuning + GraphRAG process cache."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from app.config import Settings
from app.services.learning import assistant as assistant_mod
from app.services.learning.assistant import (
    QUERY_MAX_TOKEN_COMMUNITY,
    QUERY_MAX_TOKEN_LOCAL_CONTEXT,
    QUERY_MAX_TOKEN_TEXT_UNIT,
    QUERY_TOP_K,
    _get_cached_rag,
    clear_rag_cache,
    ready_marker,
)


def test_query_params_are_lean():
    assert QUERY_TOP_K <= 6
    assert QUERY_MAX_TOKEN_TEXT_UNIT <= 1200
    assert QUERY_MAX_TOKEN_LOCAL_CONTEXT <= 1500
    assert QUERY_MAX_TOKEN_COMMUNITY <= 800


def test_rag_cache_reuses_instance(tmp_path: Path, monkeypatch):
    work = tmp_path / "job"
    nano = work / "nano_graphrag"
    nano.mkdir(parents=True)
    ready_marker(work).write_text("ready", encoding="utf-8")

    clear_rag_cache()
    calls = {"n": 0}

    def fake_make(work_dir: Path, settings: Settings):
        calls["n"] += 1
        return MagicMock(name=f"rag-{calls['n']}")

    monkeypatch.setattr(assistant_mod, "_make_graph_rag", fake_make)
    settings = Settings(use_fake_llm=True, embedding_backend="fake")

    a = _get_cached_rag(work, settings)
    b = _get_cached_rag(work, settings)
    assert a is b
    assert calls["n"] == 1

    # New ready stamp → rebuild
    ready_marker(work).write_text("ready2", encoding="utf-8")
    c = _get_cached_rag(work, settings)
    assert c is not a
    assert calls["n"] == 2

    clear_rag_cache(work)
    d = _get_cached_rag(work, settings)
    assert d is not c
    assert calls["n"] == 3
