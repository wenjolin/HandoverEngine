"""Day writer parallel LLM calls."""

from __future__ import annotations

import json
from pathlib import Path

from app.models.schemas import JobOptions, LearningPlan, LearningPlanItem
from app.pipeline.llm import FakeLLMClient
from app.pipeline.nodes.day_writer import run_day_writer
from app.services.learning.store import save_learning_plan


def test_run_day_writer_parallel_days(tmp_path: Path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(parents=True)
    (artifacts / "cards.json").write_text(
        '{"cards":[{"id":"card-001","title":"概覽","category":"overview",'
        '"summary":"s","details":"details here for teaching",'
        '"citations":[{"path":"README.md"}],'
        '"importance":"high","needs_review":false}]}',
        encoding="utf-8",
    )
    plan = LearningPlan(
        days=3,
        midterm_day=2,
        items=[
            LearningPlanItem(
                day=i,
                theme=f"第 {i} 天",
                objectives=[f"目標{i}"],
                card_ids=["card-001"],
                reads=["README.md"],
            )
            for i in range(1, 4)
        ],
    )
    save_learning_plan(tmp_path, plan)
    opts = JobOptions(days=3, language="zh-TW")
    packages = run_day_writer(
        tmp_path, opts, FakeLLMClient(), max_workers=2
    )
    assert len(packages) == 3
    assert [p.day for p in packages] == [1, 2, 3]
    for i in range(1, 4):
        day = json.loads(
            (artifacts / "days" / f"{i}.json").read_text(encoding="utf-8")
        )
        assert day["day"] == i
        assert len(day["blocks"]) >= 3
