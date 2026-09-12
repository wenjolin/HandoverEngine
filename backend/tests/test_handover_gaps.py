"""Tests for handover gaps analysis (structure + limited LLM)."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from app.config import Settings
from app.pipeline.llm import FakeLLMClient
from app.pipeline.nodes.handover_gaps import run_handover_gaps
from app.pipeline.nodes.index import run_index
from app.pipeline.nodes.ingest import run_ingest
from app.pipeline.nodes.extract import run_extract
from app.services.learning.store import load_handover_gaps


def test_handover_gaps_writes_report(tmp_path: Path):
    z = tmp_path / "input.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("README.md", "# Demo\n啟動：python app.py\n")
        zf.writestr("main.py", "def main():\n    print(1)\n")
        zf.writestr("requirements.txt", "flask\n")
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

    # Force coverage gap on main.py
    cards_path = work / "artifacts" / "cards.json"
    payload = json.loads(cards_path.read_text(encoding="utf-8"))
    payload["cards"] = [
        {
            "id": "only-readme",
            "title": "readme",
            "category": "overview",
            "summary": "概覽",
            "details": "只有 README",
            "citations": [{"path": "README.md"}],
            "importance": "high",
            "needs_review": False,
            "symbol": None,
        }
    ]
    cards_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    (work / "artifacts" / "coverage.json").write_text(
        json.dumps(
            {
                "uncovered_important_files": ["main.py"],
                "total_files": 3,
                "indexed_files": 3,
                "referenced_files": 1,
                "referenced_paths": ["README.md"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = run_handover_gaps(work, FakeLLMClient())
    out = work / "artifacts" / "handover_gaps.json"
    assert out.is_file()
    assert report["summary"]["total"] >= 1
    assert set(report["summary"]) == {
        "total",
        "coverage",
        "structure",
        "contradiction",
        "manual",
    }
    kinds = {g["kind"] for g in report["gaps"]}
    assert "coverage" in kinds
    assert "contradiction" in kinds
    for g in report["gaps"]:
        assert g.get("question")
        assert g.get("title")
        assert g["status"] == "unresolved"
        assert g["source_type"] == "auto"


def test_load_handover_gaps_upgrades_legacy_report(tmp_path: Path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "handover_gaps.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-01-01T00:00:00Z",
                "summary": {"total": 1},
                "gaps": [
                    {
                        "id": "legacy-1",
                        "kind": "coverage",
                        "severity": "medium",
                        "title": "舊缺口",
                        "detail": "",
                        "sources": [],
                        "question": "需要確認什麼？",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = load_handover_gaps(tmp_path)

    assert report["summary"] == {
        "total": 1,
        "coverage": 0,
        "structure": 0,
        "contradiction": 0,
        "manual": 0,
    }
    assert report["gaps"][0]["status"] == "unresolved"
    assert report["gaps"][0]["source_type"] == "auto"
