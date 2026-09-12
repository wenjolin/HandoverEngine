"""Progress unlock rules."""

from __future__ import annotations

from app.models.enums import DayProgressStatus
from app.models.schemas import LearningPlan, LearningPlanItem, Progress
from app.services.learning.store import recompute_progress


def _plan(days: int = 3) -> LearningPlan:
    return LearningPlan(
        days=days,
        midterm_day=max(1, days // 2),
        items=[
            LearningPlanItem(day=i, theme=f"D{i}", objectives=["o"], reads=["README.md"])
            for i in range(1, days + 1)
        ],
    )


def test_final_unlocks_only_when_all_day_quizzes_passed():
    plan = _plan(3)
    progress = Progress(
        day_status={
            "1": DayProgressStatus.passed,
            "2": DayProgressStatus.passed,
            "3": DayProgressStatus.failed,
        }
    )
    out = recompute_progress(plan, progress)
    assert out.final_unlocked is False

    progress.day_status["3"] = DayProgressStatus.passed
    out = recompute_progress(plan, progress)
    assert out.final_unlocked is True
    assert out.percent_complete == 100.0


def test_midterm_still_at_half_progress():
    plan = _plan(4)
    progress = Progress(
        day_status={
            "1": DayProgressStatus.passed,
            "2": DayProgressStatus.passed,
            "3": DayProgressStatus.unread,
            "4": DayProgressStatus.unread,
        }
    )
    out = recompute_progress(plan, progress)
    assert out.midterm_unlocked is True
    assert out.final_unlocked is False
