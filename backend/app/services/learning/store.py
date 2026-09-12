"""Load/save learning SSOT artifacts under job artifacts/."""

from __future__ import annotations

import json
from pathlib import Path

from app.models.enums import DayProgressStatus
from app.models.schemas import DayPackage, LearningPlan, Progress, QuizBank


def artifacts_dir(work_dir: Path) -> Path:
    return work_dir / "artifacts"


def write_json(path: Path, model) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        model.model_dump_json(indent=2),
        encoding="utf-8",
    )


def load_learning_plan(work_dir: Path) -> LearningPlan:
    path = artifacts_dir(work_dir) / "learning_plan.json"
    return LearningPlan.model_validate_json(path.read_text(encoding="utf-8"))


def save_learning_plan(work_dir: Path, plan: LearningPlan) -> Path:
    path = artifacts_dir(work_dir) / "learning_plan.json"
    write_json(path, plan)
    return path


def day_path(work_dir: Path, day: int) -> Path:
    return artifacts_dir(work_dir) / "days" / f"{day}.json"


def load_day_package(work_dir: Path, day: int) -> DayPackage:
    return DayPackage.model_validate_json(day_path(work_dir, day).read_text(encoding="utf-8"))


def save_day_package(work_dir: Path, pkg: DayPackage) -> Path:
    path = day_path(work_dir, pkg.day)
    write_json(path, pkg)
    return path


def load_quiz_bank(work_dir: Path) -> QuizBank:
    path = artifacts_dir(work_dir) / "quiz_bank.json"
    return QuizBank.model_validate_json(path.read_text(encoding="utf-8"))


def save_quiz_bank(work_dir: Path, bank: QuizBank) -> Path:
    path = artifacts_dir(work_dir) / "quiz_bank.json"
    write_json(path, bank)
    return path


def load_progress(work_dir: Path) -> Progress:
    path = artifacts_dir(work_dir) / "progress.json"
    return Progress.model_validate_json(path.read_text(encoding="utf-8"))


def save_progress(work_dir: Path, progress: Progress) -> Path:
    path = artifacts_dir(work_dir) / "progress.json"
    write_json(path, progress)
    return path


def initial_progress(plan: LearningPlan) -> Progress:
    return Progress(
        day_status={
            str(i): DayProgressStatus.unread for i in range(1, plan.days + 1)
        },
        percent_complete=0.0,
        midterm_unlocked=False,
        final_unlocked=False,
    )


def recompute_progress(plan: LearningPlan, progress: Progress) -> Progress:
    total = max(plan.days, 1)
    passed = sum(
        1
        for i in range(1, plan.days + 1)
        if progress.day_status.get(str(i)) == DayProgressStatus.passed
    )
    percent = round(100.0 * passed / total, 1)
    progress.percent_complete = percent
    progress.midterm_unlocked = percent >= 50.0
    # 上手驗收：必須通過「每一天」的每日查核
    progress.final_unlocked = passed == plan.days and plan.days > 0
    return progress


def load_cards_payload(work_dir: Path) -> list[dict]:
    path = artifacts_dir(work_dir) / "cards.json"
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return list(data.get("cards") or [])
    if isinstance(data, list):
        return data
    return []


def load_handover_gaps(work_dir: Path) -> dict:
    path = artifacts_dir(work_dir) / "handover_gaps.json"
    if not path.is_file():
        return {
            "generated_at": None,
            "summary": {
                "total": 0,
                "coverage": 0,
                "structure": 0,
                "contradiction": 0,
                "manual": 0,
            },
            "gaps": [],
        }
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {
            "generated_at": None,
            "summary": {
                "total": 0,
                "coverage": 0,
                "structure": 0,
                "contradiction": 0,
                "manual": 0,
            },
            "gaps": [],
        }
    summary = data.setdefault("summary", {})
    for key in ("total", "coverage", "structure", "contradiction", "manual"):
        summary.setdefault(key, 0)
    for gap in data.setdefault("gaps", []):
        if isinstance(gap, dict):
            gap.setdefault("status", "unresolved")
            gap.setdefault("source_type", "auto")
    return data


def save_handover_gaps(work_dir: Path, report: dict) -> Path:
    path = artifacts_dir(work_dir) / "handover_gaps.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
