"""Tests for curriculum repair: Planner / Worker / Critic + permissions."""

from __future__ import annotations

import json
from pathlib import Path

from app.config import Settings
from app.models.schemas import JobOptions
from app.pipeline.llm import FakeLLMClient
from app.pipeline.nodes.day_writer import run_day_writer
from app.pipeline.nodes.outline import run_outline
from app.pipeline.nodes.quiz_smith import run_quiz_smith
from app.pipeline.repair.agent import run_repair_agent
from app.pipeline.nodes.validate_curriculum import run_validate_curriculum
from app.pipeline.repair.permissions import authorize_tool


def _seed(work: Path, days: int = 3) -> tuple[JobOptions, Settings]:
    artifacts = work / "artifacts"
    artifacts.mkdir(parents=True)
    (artifacts / "cards.json").write_text(
        '{"cards":[{"id":"card-001","title":"概覽","category":"overview",'
        '"summary":"s","details":"d","citations":[{"path":"README.md"}],'
        '"importance":"high","needs_review":false}]}',
        encoding="utf-8",
    )
    opts = JobOptions(days=days, language="zh-TW")
    llm = FakeLLMClient()
    run_outline(work, opts, llm)
    run_day_writer(work, opts, llm)
    run_quiz_smith(work, opts, llm)
    settings = Settings(use_fake_llm=True, embedding_backend="fake")
    return opts, settings


def test_authorize_rejects_revalidate_and_clamps_days():
    denied = authorize_tool("revalidate", {}, max_day=5)
    assert denied.ok is False
    ok = authorize_tool("rewrite_days", {"days": [2, 99, 0, 3]}, max_day=5)
    assert ok.ok is True
    assert ok.args["days"] == [2, 3]
    search = authorize_tool("search_chunks", {"query": "x", "k": 100}, max_day=5)
    assert search.ok is True
    assert search.args["k"] == 8


def test_repair_agent_restores_missing_day(tmp_path: Path):
    opts, settings = _seed(tmp_path)
    (tmp_path / "artifacts" / "days" / "2.json").unlink()
    assert run_validate_curriculum(tmp_path, opts).ok is False

    result = run_repair_agent(
        tmp_path, opts, FakeLLMClient(), settings, issues=None
    )
    assert result.ok is True
    assert (tmp_path / "artifacts" / "days" / "2.json").is_file()
    roles = [s.get("role") for s in result.steps]
    assert "planner" in roles
    assert "worker" in roles
    assert "critic" in roles
    assert any(s.get("role") == "worker" and s.get("tool") == "rewrite_days" for s in result.steps)
    # Critic 判定通過；不應出現 LLM 自宣的 revalidate 工具
    assert not any(s.get("tool") == "revalidate" for s in result.steps)


def test_repair_agent_tops_up_quizzes(tmp_path: Path):
    opts, settings = _seed(tmp_path)
    bank_path = tmp_path / "artifacts" / "quiz_bank.json"
    bank = json.loads(bank_path.read_text(encoding="utf-8"))
    bank["day_quizzes"]["1"] = bank["day_quizzes"]["1"][:1]
    bank_path.write_text(json.dumps(bank), encoding="utf-8")

    result = run_repair_agent(
        tmp_path, opts, FakeLLMClient(), settings, issues=None
    )
    assert result.ok is True
    assert any(
        s.get("role") == "worker" and s.get("tool") == "top_up_quizzes"
        for s in result.steps
    )
    bank2 = json.loads(bank_path.read_text(encoding="utf-8"))
    assert len(bank2["day_quizzes"]["1"]) >= 3
    assert any(s.get("role") == "critic" and s.get("ok") is True for s in result.steps)
