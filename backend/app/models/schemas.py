from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from app.models.enums import (
    CardCategory,
    DayBlockType,
    DayProgressStatus,
    GapStatus,
    Importance,
    JobStatus,
)


class Citation(BaseModel):
    chunk_id: str | None = None
    path: str
    start_line: int | None = None
    end_line: int | None = None


class KnowledgeCard(BaseModel):
    id: str
    title: str
    category: CardCategory
    summary: str
    details: str
    citations: list[Citation]
    importance: Importance
    needs_review: bool = False
    symbol: str | None = None
    importance_score: float | None = None


class JobOptions(BaseModel):
    days: int = 7
    language: str = "zh-TW"


class JobProgress(BaseModel):
    step: str | None = None
    percent: int | None = None
    message: str | None = None


class JobOutputs(BaseModel):
    zip_ready: bool = False
    pdf_ready: bool = False
    plan_ready: bool = False


class JobRecord(BaseModel):
    id: str
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    input_zip_path: Path | None = None
    work_dir: Path
    output_zip_path: Path | None = None
    output_pdf_path: Path | None = None
    options: JobOptions
    progress: JobProgress = Field(default_factory=JobProgress)
    error: str | None = None


class JobPublic(BaseModel):
    id: str
    status: JobStatus
    progress: JobProgress
    options: JobOptions
    error: str | None = None
    outputs: JobOutputs

    @classmethod
    def from_record(cls, record: JobRecord) -> "JobPublic":
        work = Path(record.work_dir)
        plan_ready = (work / "artifacts" / "learning_plan.json").is_file()
        zip_ready = (
            record.output_zip_path is not None and record.output_zip_path.is_file()
        )
        pdf_ready = (
            record.output_pdf_path is not None and record.output_pdf_path.is_file()
        )
        return cls(
            id=record.id,
            status=record.status,
            progress=record.progress,
            options=record.options,
            error=record.error,
            outputs=JobOutputs(
                zip_ready=zip_ready, pdf_ready=pdf_ready, plan_ready=plan_ready
            ),
        )


class LearningPlanItem(BaseModel):
    day: int
    theme: str
    objectives: list[str] = Field(default_factory=list)
    card_ids: list[str] = Field(default_factory=list)
    reads: list[str] = Field(default_factory=list)
    pass_score: float = 1.0


class LearningPlan(BaseModel):
    days: int
    midterm_day: int
    language: str = "zh-TW"
    items: list[LearningPlanItem]


class DayBlock(BaseModel):
    type: DayBlockType
    title: str | None = None
    body: str = ""
    paths: list[str] = Field(default_factory=list)


class DayPackage(BaseModel):
    day: int
    theme: str = ""
    blocks: list[DayBlock] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)


class QuizItem(BaseModel):
    id: str
    type: str = "mcq"
    stem: str
    choices: list[str] | None = None
    answer: str
    explanation: str = ""
    citations: list[Citation] = Field(default_factory=list)


class QuizBank(BaseModel):
    day_quizzes: dict[str, list[QuizItem]] = Field(default_factory=dict)
    midterm: list[QuizItem] = Field(default_factory=list)
    final: list[QuizItem] = Field(default_factory=list)


class QuizAttempt(BaseModel):
    quiz_key: str
    score: float
    passed: bool
    at: str


class Progress(BaseModel):
    day_status: dict[str, DayProgressStatus] = Field(default_factory=dict)
    quiz_attempts: list[QuizAttempt] = Field(default_factory=list)
    percent_complete: float = 0.0
    midterm_unlocked: bool = False
    final_unlocked: bool = False


class HandoverGap(BaseModel):
    id: str
    kind: str
    severity: str
    title: str
    detail: str = ""
    sources: list[str] = Field(default_factory=list)
    question: str
    status: GapStatus = GapStatus.unresolved
    source_type: str = "auto"
    created_at: str | None = None
    updated_at: str | None = None


class GapSummary(BaseModel):
    total: int = 0
    coverage: int = 0
    structure: int = 0
    contradiction: int = 0
    manual: int = 0


class HandoverGapsReport(BaseModel):
    generated_at: str | None = None
    summary: GapSummary = Field(default_factory=GapSummary)
    gaps: list[HandoverGap] = Field(default_factory=list)


class PlanGapsResponse(HandoverGapsReport):
    id: str


class GapStatusUpdateRequest(BaseModel):
    status: GapStatus


class GapCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=160)
    question: str = Field(..., min_length=1, max_length=200)
    detail: str = ""
    sources: list[str] = Field(default_factory=list)
    status: GapStatus = GapStatus.unresolved


class QuizSubmitRequest(BaseModel):
    scope: str  # day | midterm | final
    day: int | None = None
    answers: dict[str, str] = Field(default_factory=dict)


class AssistantAskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=200)
    day: int | None = None


class AssistantAskResponse(BaseModel):
    answer: str
    mode: str = "local"
    engine: str
    citations: list[dict] = Field(default_factory=list)
    day: int | None = None
