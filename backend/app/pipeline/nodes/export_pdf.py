"""Export combined PDF from markdown artifacts + per-day notes PDFs."""

from __future__ import annotations

from pathlib import Path

from app.services.learning.store import load_day_package, load_learning_plan
from app.services.learning.pdf_export import export_day_notes_pdf, markdown_files_to_pdf


def run_export_pdf(work_dir: Path) -> Path:
    artifacts = work_dir / "artifacts"
    md_order = [
        artifacts / "00-overview.md",
        artifacts / "01-learning-plan.md",
        artifacts / "02-architecture.md",
        artifacts / "03-runbook.md",
        artifacts / "sources-index.md",
    ]
    quizzes = (
        sorted((artifacts / "quizzes").glob("*.md"))
        if (artifacts / "quizzes").is_dir()
        else []
    )
    md_order.extend(quizzes)
    pdf_path = artifacts / "handover-pack.pdf"
    markdown_files_to_pdf(md_order, pdf_path, title="Handover Learning Pack")

    plan_path = artifacts / "learning_plan.json"
    if plan_path.is_file():
        plan = load_learning_plan(work_dir)
        for i in range(1, plan.days + 1):
            day_json = artifacts / "days" / f"{i}.json"
            if not day_json.is_file():
                continue
            pkg = load_day_package(work_dir, i)
            export_day_notes_pdf(work_dir, pkg)

    return pdf_path
