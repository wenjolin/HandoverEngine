"""Acceptance contract: programmatic criteria for curriculum success."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from app.models.schemas import JobOptions

if TYPE_CHECKING:
    from app.pipeline.nodes.validate_curriculum import ValidateResult


@dataclass(frozen=True)
class AcceptanceContract:
    """What 'done' means — Critic enforces this; Planner/Worker cannot self-certify."""

    min_day_quizzes: int = 3
    min_midterm: int = 10
    min_final: int = 20
    require_day_packages: bool = True
    max_plan_rounds: int = 3
    max_worker_actions_per_round: int = 3

    def prompt_text(self, options: JobOptions) -> str:
        return (
            f"驗收契約（必須全部滿足才算成功）：\n"
            f"- learning_plan 天數完整，且與 options.days={options.days} 對齊（不一致僅警告）\n"
            f"- 每天存在 artifacts/days/{{i}}.json\n"
            f"- 每日查核 ≥ {self.min_day_quizzes} 題；交接期中查核 ≥ {self.min_midterm}；上手驗收 ≥ {self.min_final}\n"
            f"- 僅 Critic（程式驗證）可判定通過；Planner/Worker 不得自行宣布成功\n"
            f"- 規劃輪次上限 {self.max_plan_rounds}；每輪最多 {self.max_worker_actions_per_round} 個動作\n"
        )


DEFAULT_CONTRACT = AcceptanceContract()


def evaluate_contract(
    work_dir: Path,
    options: JobOptions,
    contract: AcceptanceContract | None = None,
) -> ValidateResult:
    """Critic entry: only this path may declare acceptance."""
    from app.pipeline.nodes.validate_curriculum import run_validate_curriculum

    c = contract or DEFAULT_CONTRACT
    return run_validate_curriculum(work_dir, options, contract=c)
