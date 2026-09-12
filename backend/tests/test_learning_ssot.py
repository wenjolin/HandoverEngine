from pathlib import Path

from app.models.schemas import JobOptions, LearningPlan, QuizBank, DayPackage, Progress
from app.pipeline.llm import FakeLLMClient
from app.pipeline.nodes.day_writer import run_day_writer
from app.pipeline.nodes.outline import run_outline
from app.pipeline.nodes.quiz_smith import run_quiz_smith
from app.pipeline.nodes.validate_curriculum import run_validate_curriculum


def test_phase_b_json_artifacts(tmp_path: Path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(parents=True)
    (artifacts / "cards.json").write_text(
        '{"cards":[{"id":"card-001","title":"概覽","category":"overview",'
        '"summary":"s","details":"d","citations":[{"path":"README.md"}],'
        '"importance":"high","needs_review":false}]}',
        encoding="utf-8",
    )
    opts = JobOptions(days=5, language="zh-TW")
    llm = FakeLLMClient()
    plan = run_outline(tmp_path, opts, llm)
    assert isinstance(plan, LearningPlan)
    assert plan.days == 5
    assert (artifacts / "learning_plan.json").is_file()
    LearningPlan.model_validate_json(
        (artifacts / "learning_plan.json").read_text(encoding="utf-8")
    )

    packages = run_day_writer(tmp_path, opts, llm)
    assert len(packages) == 5
    for i in range(1, 6):
        DayPackage.model_validate_json(
            (artifacts / "days" / f"{i}.json").read_text(encoding="utf-8")
        )
    assert (artifacts / "diagrams" / "architecture.mmd").is_file()

    bank = run_quiz_smith(tmp_path, opts, llm)
    assert isinstance(bank, QuizBank)
    QuizBank.model_validate_json(
        (artifacts / "quiz_bank.json").read_text(encoding="utf-8")
    )
    for i in range(1, 6):
        assert len(bank.day_quizzes[str(i)]) >= 3
    assert len(bank.midterm) >= 10
    assert len(bank.final) >= 20

    run_validate_curriculum(tmp_path, opts)
    Progress.model_validate_json(
        (artifacts / "progress.json").read_text(encoding="utf-8")
    )
