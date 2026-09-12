"""Validate curriculum soft result + repair routing."""

from __future__ import annotations

import json
from pathlib import Path

from app.models.schemas import JobOptions
from app.pipeline.nodes.validate_curriculum import (
    MAX_REPAIR_RETRIES,
    decide_validate_route,
    run_validate_curriculum,
)
from app.pipeline.llm import FakeLLMClient
from app.pipeline.nodes.day_writer import run_day_writer
from app.pipeline.nodes.outline import run_outline
from app.pipeline.nodes.quiz_smith import run_quiz_smith


def _seed_ok_curriculum(work: Path, days: int = 3) -> JobOptions:
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
    return opts


def test_validate_ok_saves_progress(tmp_path: Path):
    opts = _seed_ok_curriculum(tmp_path)
    result = run_validate_curriculum(tmp_path, opts)
    assert result.ok is True
    assert result.issues == []
    assert (tmp_path / "artifacts" / "progress.json").is_file()


def test_validate_soft_quiz_short_no_progress(tmp_path: Path):
    opts = _seed_ok_curriculum(tmp_path, days=3)
    bank_path = tmp_path / "artifacts" / "quiz_bank.json"
    bank = json.loads(bank_path.read_text(encoding="utf-8"))
    bank["day_quizzes"]["1"] = bank["day_quizzes"]["1"][:1]
    bank_path.write_text(json.dumps(bank), encoding="utf-8")

    result = run_validate_curriculum(tmp_path, opts)
    assert result.ok is False
    assert any(i["code"] == "day_quiz_short" and i.get("day") == 1 for i in result.issues)
    assert not (tmp_path / "artifacts" / "progress.json").is_file()


def test_validate_soft_missing_day(tmp_path: Path):
    opts = _seed_ok_curriculum(tmp_path, days=3)
    (tmp_path / "artifacts" / "days" / "2.json").unlink()
    result = run_validate_curriculum(tmp_path, opts)
    assert result.ok is False
    assert any(i["code"] == "missing_day_package" and i.get("day") == 2 for i in result.issues)


def test_decide_route_ok_to_render():
    assert (
        decide_validate_route(
            validate_ok=True,
            issues=[],
            repair_retries=0,
        )
        == "render_diagrams"
    )


def test_decide_route_issues_to_repair():
    issues = [
        {"code": "day_quiz_short", "day": 1, "message": "quiz"},
        {"code": "missing_day_package", "day": 2, "message": "day"},
    ]
    assert (
        decide_validate_route(
            validate_ok=False,
            issues=issues,
            repair_retries=0,
        )
        == "repair"
    )


def test_decide_route_repair_exhaust():
    issues = [{"code": "midterm_short", "message": "mid"}]
    assert (
        decide_validate_route(
            validate_ok=False,
            issues=issues,
            repair_retries=MAX_REPAIR_RETRIES,
        )
        == "fail"
    )
