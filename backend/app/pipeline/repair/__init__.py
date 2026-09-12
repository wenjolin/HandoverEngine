"""Curriculum repair: Planner → Worker → Critic.

Import agent from ``app.pipeline.repair.agent`` to avoid circular imports
with curriculum nodes that only need the contract.
"""

from app.pipeline.repair.contract import (
    DEFAULT_CONTRACT,
    AcceptanceContract,
    evaluate_contract,
)
from app.pipeline.repair.permissions import ALLOWED_WORKER_TOOLS, authorize_tool

__all__ = [
    "ALLOWED_WORKER_TOOLS",
    "AcceptanceContract",
    "DEFAULT_CONTRACT",
    "authorize_tool",
    "evaluate_contract",
]


def __getattr__(name: str):
    if name in {"run_repair_agent", "RepairResult"}:
        from app.pipeline.repair import agent as _agent

        return getattr(_agent, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
