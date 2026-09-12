"""Unit tests for coverage check / gap extract routing (P1)."""

from __future__ import annotations

import json
from pathlib import Path

from app.config import Settings
from app.models.schemas import Citation, KnowledgeCard
from app.pipeline.llm import FakeLLMClient
from app.pipeline.nodes.extract import (
    MAX_COVERAGE_RETRIES,
    decide_coverage_route,
    run_check_coverage,
    run_extract,
    run_extract_gap,
)
from app.pipeline.nodes.index import run_index
from app.pipeline.nodes.ingest import run_ingest
import zipfile


def test_decide_coverage_route():
    assert (
        decide_coverage_route(
            coverage_ok=True, uncovered_paths=[], coverage_retries=0
        )
        == "handover_gaps"
    )
    assert (
        decide_coverage_route(
            coverage_ok=False,
            uncovered_paths=["main.py"],
            coverage_retries=0,
        )
        == "extract_gap"
    )
    assert (
        decide_coverage_route(
            coverage_ok=False,
            uncovered_paths=["main.py"],
            coverage_retries=MAX_COVERAGE_RETRIES,
        )
        == "handover_gaps"
    )
    assert (
        decide_coverage_route(
            coverage_ok=False, uncovered_paths=[], coverage_retries=0
        )
        == "handover_gaps"
    )


def test_check_and_gap_extract(tmp_path: Path):
    z = tmp_path / "input.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("README.md", "# Sample\n啟動方式\n")
        zf.writestr("main.py", "def main():\n    print('hi')\n")
        zf.writestr("src/app.py", "print('app')\n")
    work = tmp_path / "job"
    work.mkdir()
    z.rename(work / "input.zip")

    settings = Settings(
        use_fake_llm=True,
        embedding_backend="fake",
        max_extract_files=100,
        max_extract_bytes=10_000_000,
    )
    run_ingest(work, settings)
    run_index(work, settings)
    run_extract(work, settings, FakeLLMClient())

    # Force uncovered important file
    payload = json.loads(
        (work / "artifacts" / "cards.json").read_text(encoding="utf-8")
    )
    payload["cards"] = [
        KnowledgeCard(
            id="only-readme",
            title="readme",
            category="overview",
            summary="s",
            details="d",
            citations=[Citation(path="README.md")],
            importance="high",
        ).model_dump()
    ]
    (work / "artifacts" / "cards.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )

    check = run_check_coverage(work)
    assert check.ok is False
    assert "main.py" in check.uncovered_paths

    before = len(payload["cards"])
    run_extract_gap(work, settings, FakeLLMClient(), check.uncovered_paths)
    after_payload = json.loads(
        (work / "artifacts" / "cards.json").read_text(encoding="utf-8")
    )
    assert len(after_payload["cards"]) >= before
    assert (work / "artifacts" / "coverage.json").is_file()
