import zipfile
from pathlib import Path

from app.pipeline.nodes.export_pdf import run_export_pdf
from app.pipeline.nodes.package import run_package
from app.pipeline.nodes.render_diagrams import run_render_diagrams
from app.services.learning.pdf_export import pdf_looks_ok


def _seed_artifacts(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(parents=True)
    (artifacts / "00-overview.md").write_text("# 概覽\n", encoding="utf-8")
    (artifacts / "01-learning-plan.md").write_text("# 計畫\n## Day 1\n", encoding="utf-8")
    (artifacts / "02-architecture.md").write_text("# 架構\n", encoding="utf-8")
    (artifacts / "03-runbook.md").write_text("# Runbook\n", encoding="utf-8")
    (artifacts / "sources-index.md").write_text("# sources\n", encoding="utf-8")
    (artifacts / "cards.json").write_text('{"cards":[]}', encoding="utf-8")
    quizzes = artifacts / "quizzes"
    quizzes.mkdir()
    (quizzes / "day1.md").write_text("# q\n", encoding="utf-8")
    diagrams = artifacts / "diagrams"
    diagrams.mkdir()
    (diagrams / "architecture.mmd").write_text(
        "flowchart LR\n  A --> B\n", encoding="utf-8"
    )


def test_render_diagrams_writes_svg(tmp_path: Path):
    _seed_artifacts(tmp_path)
    warnings = run_render_diagrams(tmp_path)
    svg = tmp_path / "artifacts" / "diagrams" / "architecture.svg"
    assert svg.exists()
    assert svg.stat().st_size > 0
    assert isinstance(warnings, list)


def test_export_pdf_writes_file(tmp_path: Path):
    _seed_artifacts(tmp_path)
    run_render_diagrams(tmp_path)
    pdf = run_export_pdf(tmp_path)
    assert pdf.exists() and pdf.stat().st_size > 100
    assert pdf.read_bytes()[:4] == b"%PDF"
    assert pdf_looks_ok(pdf)


def test_export_pdf_writes_day_notes(tmp_path: Path):
    _seed_artifacts(tmp_path)
    artifacts = tmp_path / "artifacts"
    days = artifacts / "days"
    days.mkdir(parents=True)
    (artifacts / "learning_plan.json").write_text(
        '{"days":1,"midterm_day":1,"language":"zh-TW","items":[{"day":1,"theme":"t","objectives":[],"card_ids":[],"reads":[]}]}',
        encoding="utf-8",
    )
    (days / "1.json").write_text(
        '{"day":1,"theme":"啟動","blocks":[{"type":"goal","title":"目標","body":"跑起來","paths":[]}],"source_refs":["README.md"]}',
        encoding="utf-8",
    )
    run_export_pdf(tmp_path)
    notes = days / "1-notes.pdf"
    assert notes.exists() and notes.read_bytes()[:4] == b"%PDF"
    assert pdf_looks_ok(notes)


def test_package_contains_expected_members(tmp_path: Path):
    _seed_artifacts(tmp_path)
    run_render_diagrams(tmp_path)
    run_export_pdf(tmp_path)
    zpath = run_package(tmp_path)
    with zipfile.ZipFile(zpath) as zf:
        names = zf.namelist()
    assert any(n.endswith("01-learning-plan.md") for n in names)
    assert any(n.endswith("handover-pack.pdf") for n in names)
    assert any("diagrams/" in n for n in names)
