"""Package artifacts into handover-pack.zip."""

from __future__ import annotations

import zipfile
from pathlib import Path


def run_package(work_dir: Path) -> Path:
    artifacts = work_dir / "artifacts"
    out_zip = work_dir / "handover-pack.zip"
    if not artifacts.is_dir():
        raise ValueError("缺少 artifacts 目錄")

    pdf = artifacts / "handover-pack.pdf"
    if not pdf.is_file():
        raise ValueError("缺少 handover-pack.pdf，無法打包")

    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        mapping = [
            ("00-overview.md", "handover-pack/00-overview.md"),
            ("01-learning-plan.md", "handover-pack/01-learning-plan.md"),
            ("02-architecture.md", "handover-pack/02-architecture.md"),
            ("03-runbook.md", "handover-pack/03-runbook.md"),
            ("sources-index.md", "handover-pack/sources-index.md"),
            ("cards.json", "handover-pack/knowledge/cards.json"),
            ("learning_plan.json", "handover-pack/learning_plan.json"),
            ("quiz_bank.json", "handover-pack/quiz_bank.json"),
            ("progress.json", "handover-pack/progress.json"),
            ("handover_gaps.json", "handover-pack/handover_gaps.json"),
            ("handover-pack.pdf", "handover-pack/handover-pack.pdf"),
        ]
        for src_name, arc in mapping:
            src = artifacts / src_name
            if src.is_file():
                zf.write(src, arcname=arc)

        days_dir = artifacts / "days"
        if days_dir.is_dir():
            for d in days_dir.glob("*.json"):
                zf.write(d, arcname=f"handover-pack/days/{d.name}")
            for pdf in days_dir.glob("*-notes.pdf"):
                zf.write(pdf, arcname=f"handover-pack/days/{pdf.name}")

        quizzes = artifacts / "quizzes"
        if quizzes.is_dir():
            for q in quizzes.glob("*.md"):
                zf.write(q, arcname=f"handover-pack/quizzes/{q.name}")

        diagrams = artifacts / "diagrams"
        if diagrams.is_dir():
            for d in diagrams.iterdir():
                if d.is_file():
                    zf.write(d, arcname=f"handover-pack/diagrams/{d.name}")

    return out_zip
