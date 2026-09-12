"""Repair loop: Planner (LLM) → Worker (tools) → Critic (contract)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import Settings
from app.models.schemas import JobOptions
from app.pipeline.repair.contract import (
    DEFAULT_CONTRACT,
    AcceptanceContract,
    evaluate_contract,
)
from app.pipeline.llm import LLMClient
from app.pipeline.nodes.day_writer import rewrite_day_packages
from app.pipeline.nodes.quiz_smith import top_up_quiz_bank
from app.pipeline.nodes.validate_curriculum import ValidateResult
from app.pipeline.repair.permissions import ALLOWED_WORKER_TOOLS, authorize_tool
from app.services.indexing.chroma_store import ChromaStore
from app.services.learning.store import load_learning_plan

logger = logging.getLogger(__name__)

PLANNER_SYSTEM = """你是「課綱修復規劃師（Planner）」。你只負責提出下一個 Worker 動作，不能宣布驗收通過。

每次只輸出一個 JSON：
{"tool":"<名稱>","args":{...}}
或結束本輪規劃：{"tool":"stop_planning","args":{}}

Worker 可用工具（白名單）：
- list_issues：查看目前 issues（args 空）
- rewrite_days：補每日教材，args={"days":[2,3]}（天數須在契約範圍內）
- top_up_quizzes：補足小測／期中／期末題數（args 空）
- search_chunks：搜尋索引，args={"query":"...","k":4}

規則：
1. 先修 missing_day_package／plan_incomplete，再修題數不足。
2. 不要輸出 revalidate／done；驗收只由 Critic（程式契約）執行。
3. 若暫時無合適動作，輸出 stop_planning。
只輸出 JSON。
"""


@dataclass
class RepairResult:
    ok: bool
    issues: list[dict[str, Any]] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)
    validate: ValidateResult | None = None
    contract_text: str = ""


def _search_chunks(
    work_dir: Path, settings: Settings, query: str, k: int = 4
) -> list[dict]:
    store = ChromaStore(
        work_dir / "index",
        embedding_backend=settings.embedding_backend,
        openai_api_key=settings.embedding_api_key or settings.openai_api_key,
        openai_base_url=settings.embedding_base_url or settings.openai_base_url,
        embedding_model=settings.embedding_model,
    )
    return store.query(query, k=k)


def _worker_execute(
    tool: str,
    args: dict[str, Any],
    *,
    work_dir: Path,
    settings: Settings,
    issues: list[dict[str, Any]],
) -> dict[str, Any]:
    if tool == "list_issues":
        return {"issues": issues}

    if tool == "rewrite_days":
        days = list(args.get("days") or [])
        if not days:
            days = [
                int(i["day"])
                for i in issues
                if i.get("code") == "missing_day_package" and i.get("day") is not None
            ]
        pkgs = rewrite_day_packages(work_dir, days)
        return {"rewritten": [p.day for p in pkgs], "count": len(pkgs)}

    if tool == "top_up_quizzes":
        bank = top_up_quiz_bank(work_dir)
        return {
            "days": {k: len(v) for k, v in bank.day_quizzes.items()},
            "midterm": len(bank.midterm),
            "final": len(bank.final),
        }

    if tool == "search_chunks":
        hits = _search_chunks(
            work_dir, settings, str(args.get("query") or "README"), k=int(args.get("k") or 4)
        )
        return {
            "hits": [
                {
                    "path": h.get("path"),
                    "start_line": h.get("start_line"),
                    "score": h.get("score"),
                    "text": (h.get("text") or "")[:200],
                }
                for h in hits
            ]
        }

    return {"error": f"worker 無法執行：{tool}"}


def _planner_next(
    llm: LLMClient,
    *,
    contract_text: str,
    issues: list[dict[str, Any]],
    round_i: int,
    max_rounds: int,
    last_worker: str,
    last_obs: Any,
) -> dict[str, Any]:
    user = (
        f"{contract_text}\n"
        f"plan_round={round_i}/{max_rounds}\n"
        f"last_worker_tool={last_worker}\n"
        f"last_worker_observation={json.dumps(last_obs, ensure_ascii=False)}\n"
        f"issues={json.dumps(issues, ensure_ascii=False)}\n"
        f"allowed_tools={sorted(ALLOWED_WORKER_TOOLS)}\n"
    )
    data = llm.complete_json(PLANNER_SYSTEM, user, dict)
    if not isinstance(data, dict):
        return {"tool": "stop_planning", "args": {}}
    return data


def run_repair_agent(
    work_dir: Path,
    options: JobOptions,
    llm: LLMClient,
    settings: Settings,
    *,
    issues: list[dict[str, Any]] | None = None,
    contract: AcceptanceContract | None = None,
) -> RepairResult:
    """Planner proposes → Worker executes (permissioned) → Critic evaluates contract."""
    contract = contract or DEFAULT_CONTRACT
    contract_text = contract.prompt_text(options)
    steps: list[dict[str, Any]] = []

    try:
        max_day = load_learning_plan(work_dir).days
    except Exception:
        max_day = options.days

    # 初始 Critic
    critic = evaluate_contract(work_dir, options, contract)
    steps.append(
        {
            "role": "critic",
            "ok": critic.ok,
            "issues": critic.issues,
            "warnings": critic.warnings,
        }
    )
    if critic.ok:
        return RepairResult(
            ok=True,
            issues=[],
            steps=steps,
            validate=critic,
            contract_text=contract_text,
        )

    current_issues = list(issues or critic.issues)
    last_worker = "none"
    last_obs: Any = None

    for round_i in range(1, contract.max_plan_rounds + 1):
        actions_this_round = 0
        while actions_this_round < contract.max_worker_actions_per_round:
            plan = _planner_next(
                llm,
                contract_text=contract_text,
                issues=current_issues,
                round_i=round_i,
                max_rounds=contract.max_plan_rounds,
                last_worker=last_worker,
                last_obs=last_obs,
            )
            tool = str(plan.get("tool") or "stop_planning")
            raw_args = plan.get("args") if isinstance(plan.get("args"), dict) else {}
            steps.append(
                {
                    "role": "planner",
                    "round": round_i,
                    "tool": tool,
                    "args": raw_args,
                }
            )

            if tool == "stop_planning":
                break

            proposed_args = dict(raw_args)
            if tool == "rewrite_days" and not proposed_args.get("days"):
                proposed_args["days"] = [
                    int(i["day"])
                    for i in current_issues
                    if i.get("code") == "missing_day_package" and i.get("day") is not None
                ]

            auth = authorize_tool(tool, proposed_args, max_day=max_day)
            if not auth.ok:
                steps.append(
                    {
                        "role": "permission_denied",
                        "tool": auth.tool,
                        "error": auth.error,
                    }
                )
                last_worker = "permission_denied"
                last_obs = {"error": auth.error}
                actions_this_round += 1
                continue

            obs = _worker_execute(
                auth.tool,
                auth.args,
                work_dir=work_dir,
                settings=settings,
                issues=current_issues,
            )
            steps.append(
                {
                    "role": "worker",
                    "tool": auth.tool,
                    "args": auth.args,
                    "observation": obs,
                }
            )
            last_worker = auth.tool
            last_obs = obs
            actions_this_round += 1

            if auth.tool == "list_issues":
                continue

        # 每輪規劃結束 → Critic（唯一可宣布 ok）
        critic = evaluate_contract(work_dir, options, contract)
        steps.append(
            {
                "role": "critic",
                "round": round_i,
                "ok": critic.ok,
                "issues": critic.issues,
                "warnings": critic.warnings,
            }
        )
        current_issues = list(critic.issues)
        if critic.ok:
            return RepairResult(
                ok=True,
                issues=[],
                steps=steps,
                validate=critic,
                contract_text=contract_text,
            )

    return RepairResult(
        ok=False,
        issues=critic.issues,
        steps=steps,
        validate=critic,
        contract_text=contract_text,
    )
