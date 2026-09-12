"""Validate curriculum SSOT against acceptance contract; init progress.json."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.models.schemas import JobOptions
from app.pipeline.repair.contract import DEFAULT_CONTRACT, AcceptanceContract
from app.services.learning.store import (
    day_path,
    initial_progress,
    load_learning_plan,
    load_quiz_bank,
    save_progress,
)

MAX_REPAIR_RETRIES = 2

_DAY_ISSUE_CODES = frozenset({"plan_incomplete", "missing_day_package"})
_QUIZ_ISSUE_CODES = frozenset({"day_quiz_short", "midterm_short", "final_short"})
_REPAIRABLE = _DAY_ISSUE_CODES | _QUIZ_ISSUE_CODES


@dataclass
class ValidateResult:
    ok: bool
    warnings: list[str] = field(default_factory=list)
    issues: list[dict[str, Any]] = field(default_factory=list)


def run_validate_curriculum(
    work_dir: Path,
    options: JobOptions,
    contract: AcceptanceContract | None = None,
) -> ValidateResult:
    """Check curriculum artifacts. On success, write progress.json. Never raises for content gaps."""
    c = contract or DEFAULT_CONTRACT
    warnings: list[str] = []
    issues: list[dict[str, Any]] = []

    plan = load_learning_plan(work_dir)
    if plan.days != options.days:
        warnings.append(f"plan.days={plan.days} 與 options.days={options.days} 不一致")
    if len(plan.items) != plan.days:
        issues.append(
            {
                "code": "plan_incomplete",
                "message": (
                    f"學習計畫天數不完整：期望 {plan.days}，實際 {len(plan.items)}"
                ),
            }
        )

    if c.require_day_packages:
        for i in range(1, plan.days + 1):
            p = day_path(work_dir, i)
            if not p.is_file():
                issues.append(
                    {
                        "code": "missing_day_package",
                        "day": i,
                        "message": f"缺少 DayPackage：days/{i}.json",
                    }
                )

    bank = load_quiz_bank(work_dir)
    for i in range(1, plan.days + 1):
        qs = bank.day_quizzes.get(str(i), [])
        if len(qs) < c.min_day_quizzes:
            issues.append(
                {
                    "code": "day_quiz_short",
                    "day": i,
                    "message": (
                        f"Day {i} 小測不足 {c.min_day_quizzes} 題（目前 {len(qs)}）"
                    ),
                }
            )
    if len(bank.midterm) < c.min_midterm:
        issues.append(
            {
                "code": "midterm_short",
                "message": (
                    f"期中測驗不足 {c.min_midterm} 題（目前 {len(bank.midterm)}）"
                ),
            }
        )
    if len(bank.final) < c.min_final:
        issues.append(
            {
                "code": "final_short",
                "message": f"期末測驗不足 {c.min_final} 題（目前 {len(bank.final)}）",
            }
        )

    if issues:
        return ValidateResult(ok=False, warnings=warnings, issues=issues)

    save_progress(work_dir, initial_progress(plan))
    return ValidateResult(ok=True, warnings=warnings, issues=[])


def decide_validate_route(
    *,
    validate_ok: bool,
    issues: list[dict[str, Any]],
    repair_retries: int = 0,
) -> str:
    """Rule router: send content gaps to repair agent, else render or fail."""
    if validate_ok:
        return "render_diagrams"
    codes = {str(i.get("code") or "") for i in issues}
    if codes & _REPAIRABLE and repair_retries < MAX_REPAIR_RETRIES:
        return "repair"
    return "fail"
