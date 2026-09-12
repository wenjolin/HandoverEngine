"""Assistant query tuning + GraphRAG process cache."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.config import Settings
from app.services.learning import assistant as assistant_mod
from app.services.learning.assistant import (
    QUERY_MAX_TOKEN_COMMUNITY,
    QUERY_MAX_TOKEN_LOCAL_CONTEXT,
    QUERY_MAX_TOKEN_TEXT_UNIT,
    QUERY_TOP_K,
    _build_llm_funcs,
    _corrupt_vdb_files,
    _embedding_dim,
    _get_cached_rag,
    _uses_max_completion_tokens,
    ask_assistant,
    clear_rag_cache,
    ensure_assistant_index,
    ready_marker,
)


def test_query_params_are_lean():
    assert QUERY_TOP_K <= 6
    assert QUERY_MAX_TOKEN_TEXT_UNIT <= 1200
    assert QUERY_MAX_TOKEN_LOCAL_CONTEXT <= 1500
    assert QUERY_MAX_TOKEN_COMMUNITY <= 800


def test_embedding_dimensions_match_openai_models():
    assert (
        _embedding_dim(
            Settings(embedding_backend="openai", embedding_model="text-embedding-3-small")
        )
        == 1536
    )


def test_gpt5_uses_max_completion_tokens(monkeypatch):
    calls: list[dict] = []

    class FakeCompletions:
        async def create(self, **kwargs):
            calls.append(kwargs)
            message = SimpleNamespace(content="ok")
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    class FakeAsyncOpenAI:
        def __init__(self, **_kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    monkeypatch.setattr(assistant_mod, "AsyncOpenAI", FakeAsyncOpenAI)
    settings = Settings(
        openai_api_key="test-key",
        openai_model="gpt-5.4-mini",
        embedding_backend="openai",
        embedding_api_key="test-key",
    )
    complete, _ = _build_llm_funcs(settings)

    assert asyncio.run(complete("prompt", max_tokens=321)) == "ok"
    assert asyncio.run(complete("second loop", max_tokens=123)) == "ok"
    assert _uses_max_completion_tokens(settings.openai_model)
    assert calls[0]["max_completion_tokens"] == 321
    assert calls[1]["max_completion_tokens"] == 123
    assert "max_tokens" not in calls[0]
    assert (
        _embedding_dim(
            Settings(embedding_backend="openai", embedding_model="text-embedding-3-large")
        )
        == 3072
    )
    assert (
        _embedding_dim(
            Settings(embedding_backend="openai", embedding_model="text-embedding-ada-002")
        )
        == 1536
    )


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


def test_corrupt_nano_vector_index_is_rebuilt(tmp_path: Path, monkeypatch):
    work = tmp_path / "job"
    nano = work / "nano_graphrag"
    nano.mkdir(parents=True)
    vdb = nano / "vdb_entities.json"
    vdb.write_text(
        json.dumps(
            {
                "embedding_dim": 1536,
                "data": [{"__id__": "entity-1"}],
                "matrix": "",
            }
        ),
        encoding="utf-8",
    )
    ready_marker(work).write_text("ready", encoding="utf-8")
    assert _corrupt_vdb_files(work) == [vdb]

    rag = MagicMock()
    monkeypatch.setattr(assistant_mod, "_make_graph_rag", lambda *_: rag)
    monkeypatch.setattr(assistant_mod, "collect_corpus", lambda _: ["demo"])
    settings = Settings(
        use_fake_llm=False,
        openai_api_key="test-key",
        embedding_backend="openai",
        embedding_api_key="test-key",
    )

    ensure_assistant_index(work, settings)

    rag.insert.assert_called_once_with(["demo"])
    assert ready_marker(work).read_text(encoding="utf-8") == "ready"
    assert not vdb.exists()


def test_assistant_raises_when_graph_index_fails(tmp_path: Path, monkeypatch):
    settings = Settings(
        use_fake_llm=False,
        openai_api_key="test-key",
        embedding_backend="openai",
        embedding_api_key="test-key",
    )
    def fail_index(*_args, **_kwargs):
        raise IndexError("broken matrix")

    monkeypatch.setattr(assistant_mod, "ensure_assistant_index", fail_index)

    with pytest.raises(IndexError, match="broken matrix"):
        ask_assistant(tmp_path / "job", "怎麼啟動？", day=2, settings=settings)


def test_graph_index_retries_once_then_raises(tmp_path: Path, monkeypatch):
    work = tmp_path / "job"
    calls = {"count": 0}

    def always_fail(*_args, **_kwargs):
        calls["count"] += 1
        raise IndexError("still broken")

    monkeypatch.setattr(assistant_mod, "collect_corpus", lambda _: ["demo"])
    monkeypatch.setattr(assistant_mod, "_insert_graph_index", always_fail)
    settings = Settings(use_fake_llm=False, openai_api_key="test-key")

    with pytest.raises(IndexError, match="still broken"):
        ensure_assistant_index(work, settings)
    assert calls["count"] == 2
    assert not ready_marker(work).exists()
