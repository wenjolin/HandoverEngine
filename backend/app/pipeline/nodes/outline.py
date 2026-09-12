"""Outline node: LearningPlan JSON + legacy markdown."""

from __future__ import annotations

import json
from pathlib import Path

from app.models.schemas import JobOptions, LearningPlan, LearningPlanItem
from app.pipeline.llm import LLMClient
from app.pipeline.prompts import PLAN_SYSTEM
from app.services.learning.store import load_cards_payload, save_learning_plan


def _fallback_plan(days: int, cards: list[dict], language: str) -> LearningPlan:
    mid = max(1, days // 2)
    card_ids = [str(c.get("id")) for c in cards if c.get("id")]
    paths: list[str] = []
    for c in cards:
        for cit in c.get("citations") or []:
            p = cit.get("path")
            if p and p not in paths:
                paths.append(p)
    if not paths:
        paths = ["README.md"]
    items: list[LearningPlanItem] = []
    for i in range(1, days + 1):
        path = paths[(i - 1) % len(paths)]
        cid = card_ids[(i - 1) % len(card_ids)] if card_ids else None
        items.append(
            LearningPlanItem(
                day=i,
                theme=f"第 {i} 天交接重點",
                objectives=[f"完成第 {i} 天必讀與檢查清單"],
                card_ids=[cid] if cid else [],
                reads=[path],
                pass_score=0.6,
            )
        )
    return LearningPlan(days=days, midterm_day=mid, language=language, items=items)


def _normalize_plan(data: dict, days: int, language: str, cards: list[dict]) -> LearningPlan:
    raw_items = data.get("items") or data.get("days")
    if isinstance(raw_items, int):
        raw_items = None
    if not isinstance(raw_items, list) or not raw_items:
        return _fallback_plan(days, cards, language)

    items: list[LearningPlanItem] = []
    for i, row in enumerate(raw_items, start=1):
        if not isinstance(row, dict):
            continue
        day_n = int(row.get("day") or i)
        theme = row.get("theme") or row.get("goal") or f"第 {day_n} 天"
        objectives = row.get("objectives") or row.get("tasks") or []
        if isinstance(objectives, str):
            objectives = [objectives]
        reads = row.get("reads") or []
        card_ids = row.get("card_ids") or []
        items.append(
            LearningPlanItem(
                day=day_n,
                theme=str(theme),
                objectives=[str(x) for x in objectives],
                card_ids=[str(x) for x in card_ids],
                reads=[str(x) for x in reads],
                pass_score=float(row.get("pass_score") or 0.6),
            )
        )

    # ensure exactly `days` items
    by_day = {it.day: it for it in items}
    normalized: list[LearningPlanItem] = []
    for i in range(1, days + 1):
        if i in by_day:
            normalized.append(by_day[i])
        else:
            normalized.append(
                LearningPlanItem(day=i, theme=f"第 {i} 天交接重點", objectives=[], reads=[])
            )

    mid = int(data.get("midterm_day") or max(1, days // 2))
    mid = min(max(1, mid), days)
    return LearningPlan(days=days, midterm_day=mid, language=language, items=normalized)


def _write_plan_md(artifacts: Path, plan: LearningPlan) -> None:
    lines = ["# 交接學習計畫", "", f"期中日：Day {plan.midterm_day}", ""]
    for item in plan.items:
        lines.append(f"## Day {item.day} — {item.theme}")
        lines.append("")
        if item.objectives:
            lines.append("**目標：**")
            for o in item.objectives:
                lines.append(f"- {o}")
            lines.append("")
        if item.reads:
            lines.append("**必讀：**")
            for r in item.reads:
                lines.append(f"- `{r}`")
            lines.append("")
        if item.card_ids:
            lines.append("**相關卡片：** " + ", ".join(item.card_ids))
            lines.append("")
    (artifacts / "01-learning-plan.md").write_text("\n".join(lines), encoding="utf-8")


def run_outline(work_dir: Path, options: JobOptions, llm: LLMClient) -> LearningPlan:
    artifacts = work_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    cards = load_cards_payload(work_dir)
    user = (
        f"days={options.days}\nlanguage={options.language}\n"
        f"cards={json.dumps(cards, ensure_ascii=False)}"
    )
    data = llm.complete_json(PLAN_SYSTEM, user, dict)
    if not isinstance(data, dict):
        data = {}
    plan = _normalize_plan(data, options.days, options.language, cards)
    save_learning_plan(work_dir, plan)
    _write_plan_md(artifacts, plan)
    return plan
