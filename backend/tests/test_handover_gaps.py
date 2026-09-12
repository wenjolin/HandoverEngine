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
    kinds = {g["kind"] for g in report["gaps"]}
    assert "coverage" in kinds
    assert "contradiction" in kinds
    for g in report["gaps"]:
        assert g.get("question")
        assert g.get("title")
