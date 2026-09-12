"""LangGraph state for handover pipeline."""

from __future__ import annotations

from typing import Any, TypedDict


class HandoverState(TypedDict, total=False):
    work_dir: str
    # coverage gap loop
    coverage_ok: bool
    uncovered_paths: list[str]
    coverage_retries: int
    coverage_route: str
    # validate + repair agent loop
    validate_ok: bool
    validate_issues: list[dict[str, Any]]
    validate_warnings: list[str]
    validate_route: str
    repair_retries: int
    repair_steps: list[dict[str, Any]]
