"""Learning runtime API: days, quizzes, notes PDF, assistant."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from pathlib import Path

import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse

from app.api.jobs import get_repo
from app.models.enums import DayProgressStatus, JobStatus
from app.models.schemas import (
    AssistantAskRequest,
    AssistantAskResponse,
    GapCreateRequest,
    GapStatusUpdateRequest,
    PlanGapsResponse,
    QuizAttempt,
    QuizItem,
    QuizSubmitRequest,
)
from app.services.learning.assistant import (
    MAX_QUESTION_CHARS,
    AssistantRequestError,
    ask_assistant,
)
from app.services.learning.store import (
    load_day_package,
    load_handover_gaps,
    load_learning_plan,
    load_progress,
    load_quiz_bank,
    recompute_progress,
    save_handover_gaps,
    save_progress,
)
from app.services.learning.pdf_export import (
    day_notes_pdf_path,
    ensure_day_notes_pdf,
    export_handover_gaps_pdf,
)
from app.services.learning.quiz_utils import answers_match, normalize_day_key
from app.services.rate_limit import SlidingWindowRateLimiter
from app.services.secrets_filter import is_ignored_path, is_secret_path

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/plans", tags=["plans"])

# 每個計畫：60 秒內最多 20 次小助手提問（防刷費用）
_assistant_limiter = SlidingWindowRateLimiter(max_calls=20, window_seconds=60.0)


def _work_dir(plan_id: str) -> Path:
    repo = get_repo()
    job = repo.get(plan_id)
    if job is None:
        raise HTTPException(status_code=404, detail="找不到學習計畫")
    if job.status != JobStatus.done:
        raise HTTPException(status_code=409, detail="Job 尚未完成")
    work = Path(job.work_dir)
    if not (work / "artifacts" / "learning_plan.json").is_file():
        raise HTTPException(status_code=409, detail="學習計畫尚未就緒")
    return work


def _public_items(items: list[QuizItem], *, include_answers: bool = False) -> list[dict]:
    out = []
    for q in items:
        item = {
            "id": q.id,
            "type": q.type,
            "stem": q.stem,
            "choices": q.choices,
            "citations": [c.model_dump() for c in q.citations],
        }
        if include_answers:
            item["answer"] = q.answer
            item["explanation"] = q.explanation
        out.append(item)
    return out


def _quiz_attempt_status(progress, quiz_key: str) -> str:
    """Return the persistent display state for a milestone quiz."""
    attempts = [attempt for attempt in progress.quiz_attempts if attempt.quiz_key == quiz_key]
    if any(attempt.passed for attempt in attempts):
        return "passed"
    return "failed" if attempts else "unread"


def _grade(items: list[QuizItem], answers: dict[str, str], pass_score: float) -> dict:
    if not items:
        return {"score": 0.0, "passed": False, "total": 0, "correct": 0}
    correct = 0
    details = []
    for q in items:
        given = (answers.get(q.id) or "").strip()
        ok = answers_match(given, q)
        if ok:
            correct += 1
        details.append(
            {
                "id": q.id,
                "correct": ok,
                "answer": q.answer,
                "explanation": q.explanation,
            }
        )
    score = correct / len(items)
    return {
        "score": round(score, 3),
        "passed": score >= pass_score,
        "total": len(items),
        "correct": correct,
        "details": details,
    }


def _day_quiz_items(bank, day: int) -> list[QuizItem]:
    key = str(day)
    items = bank.day_quizzes.get(key)
    if items:
        return items
    # tolerate legacy keys still present in older quiz_bank.json
    for k, v in bank.day_quizzes.items():
        if normalize_day_key(k) == key:
            return v
    return []


@router.get("/{plan_id}")
def get_plan(plan_id: str) -> dict:
    work = _work_dir(plan_id)
    plan = load_learning_plan(work)
    progress = recompute_progress(plan, load_progress(work))
    save_progress(work, progress)
    return {
        "id": plan_id,
        "plan": plan.model_dump(),
        "progress": progress.model_dump(),
    }


@router.get("/{plan_id}/gaps", response_model=PlanGapsResponse)
def get_gaps(plan_id: str) -> dict:
    work = _work_dir(plan_id)
    report = load_handover_gaps(work)
    return {"id": plan_id, **report}


@router.patch("/{plan_id}/gaps/{gap_id}", response_model=PlanGapsResponse)
def update_gap_status(
    plan_id: str, gap_id: str, body: GapStatusUpdateRequest
) -> dict:
    work = _work_dir(plan_id)
    report = load_handover_gaps(work)
    for gap in report.get("gaps", []):
        if isinstance(gap, dict) and gap.get("id") == gap_id:
            gap["status"] = body.status.value
            gap["updated_at"] = datetime.now(timezone.utc).isoformat()
            save_handover_gaps(work, report)
            return {"id": plan_id, **report}
    raise HTTPException(status_code=404, detail="找不到此交接缺口")


@router.post("/{plan_id}/gaps", status_code=201, response_model=PlanGapsResponse)
def create_manual_gap(plan_id: str, body: GapCreateRequest) -> dict:
    work = _work_dir(plan_id)
    report = load_handover_gaps(work)
    now = datetime.now(timezone.utc).isoformat()
    gap = {
        "id": f"manual-{uuid.uuid4().hex[:8]}",
        "kind": "manual",
        "severity": "medium",
        "title": body.title,
        "detail": body.detail,
        "sources": body.sources[:8],
        "question": body.question,
        "status": body.status.value,
        "source_type": "manual",
        "created_at": now,
        "updated_at": now,
    }
    report.setdefault("gaps", []).append(gap)
    summary = report.setdefault("summary", {})
    summary["total"] = int(summary.get("total", 0)) + 1
    summary["manual"] = int(summary.get("manual", 0)) + 1
    save_handover_gaps(work, report)
    return {"id": plan_id, **report}


@router.get("/{plan_id}/gaps/export")
def export_gaps(plan_id: str, status: str = "unresolved") -> PlainTextResponse:
    if status not in {"unresolved", "confirmed", "resolved", "all"}:
        raise HTTPException(status_code=422, detail="status 無效")
    report = load_handover_gaps(_work_dir(plan_id))
    gaps = report.get("gaps", [])
    if status != "all":
        gaps = [g for g in gaps if g.get("status", "unresolved") == status]
    labels = {"coverage": "覆蓋", "structure": "結構", "contradiction": "矛盾", "manual": "手動新增"}
    lines = [f"交接缺口問題清單（{len(gaps)} 項）", ""]
    for index, gap in enumerate(gaps, start=1):
        lines.extend([
            f"{index}. [{labels.get(gap.get('kind'), gap.get('kind', ''))}] {gap.get('title', '')}",
            f"   疑問：{gap.get('question', '')}",
        ])
        if gap.get("sources"):
            lines.append(f"   依據：{', '.join(gap['sources'])}")
        lines.append("")
    return PlainTextResponse(
        "\n".join(lines),
        headers={"Content-Disposition": "attachment; filename=handover-gaps-questions.txt"},
    )


@router.get("/{plan_id}/gaps/export/pdf")
def export_gaps_pdf(plan_id: str, status: str = "all", ids: str | None = None) -> FileResponse:
    if status not in {"unresolved", "confirmed", "resolved", "all"}:
        raise HTTPException(status_code=422, detail="status 無效")
    work = _work_dir(plan_id)
    gaps = load_handover_gaps(work).get("gaps", [])
    selected_ids = {gap_id for gap_id in (ids or "").split(",") if gap_id}
    if selected_ids:
        gaps = [gap for gap in gaps if str(gap.get("id")) in selected_ids]
    elif status != "all":
        gaps = [gap for gap in gaps if gap.get("status", "unresolved") == status]
    try:
        pdf_path = export_handover_gaps_pdf(work, gaps)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"產生交接缺口 PDF 失敗：{exc}") from exc
    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename="handover-gaps-questions.pdf",
    )


@router.get("/{plan_id}/days/{day}")
def get_day(plan_id: str, day: int) -> dict:
    work = _work_dir(plan_id)
    plan = load_learning_plan(work)
    if day < 1 or day > plan.days:
        raise HTTPException(status_code=404, detail="天數不存在")
    pkg = load_day_package(work, day)
    progress = load_progress(work)
    key = str(day)
    if progress.day_status.get(key) == DayProgressStatus.unread:
        progress.day_status[key] = DayProgressStatus.reading
    # 每次讀取都重算解鎖狀態，避免舊 progress.json 殘留上手驗收的解鎖值
    progress = recompute_progress(plan, progress)
    save_progress(work, progress)
    notes_ready = day_notes_pdf_path(work, day).is_file()
    return {
        "day": pkg.model_dump(),
        "progress": progress.model_dump(),
        "notes_pdf": f"/api/plans/{plan_id}/days/{day}/notes.pdf",
        "notes_pdf_ready": notes_ready,
    }


@router.get("/{plan_id}/days/{day}/notes.pdf")
def download_day_notes(plan_id: str, day: int) -> FileResponse:
    work = _work_dir(plan_id)
    plan = load_learning_plan(work)
    if day < 1 or day > plan.days:
        raise HTTPException(status_code=404, detail="天數不存在")
    if not (work / "artifacts" / "days" / f"{day}.json").is_file():
        raise HTTPException(status_code=404, detail="找不到當日教材")
    try:
        pdf_path = ensure_day_notes_pdf(work, day)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"產生筆記 PDF 失敗：{exc}") from exc
    return FileResponse(
        path=pdf_path,
        filename=f"day-{day}-notes.pdf",
        media_type="application/pdf",
    )


@router.get("/{plan_id}/days/{day}/files/{file_path:path}")
def get_day_file(plan_id: str, day: int, file_path: str):
    work = _work_dir(plan_id)
    plan = load_learning_plan(work)
    if day < 1 or day > plan.days:
        raise HTTPException(status_code=404, detail="天數不存在")
    rel = file_path.replace("\\", "/").lstrip("/")
    if ".." in rel.split("/") or is_ignored_path(rel) or is_secret_path(rel):
        raise HTTPException(status_code=403, detail="不允許讀取此路徑")
    raw = work / "raw" / rel
    if not raw.is_file():
        raise HTTPException(status_code=404, detail="檔案不存在")
    # ensure under raw
    try:
        raw.resolve().relative_to((work / "raw").resolve())
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="路徑非法") from exc
    return FileResponse(raw)


@router.get("/{plan_id}/quizzes/day/{day}")
def get_day_quiz(plan_id: str, day: int) -> dict:
    work = _work_dir(plan_id)
    plan = load_learning_plan(work)
    if day < 1 or day > plan.days:
        raise HTTPException(status_code=404, detail="天數不存在")
    bank = load_quiz_bank(work)
    items = _day_quiz_items(bank, day)
    progress = load_progress(work)
    review_mode = progress.day_status.get(str(day)) == DayProgressStatus.passed
    return {
        "scope": "day",
        "day": day,
        "review_mode": review_mode,
        "items": _public_items(items, include_answers=review_mode),
    }


@router.get("/{plan_id}/quizzes/midterm")
def get_midterm(plan_id: str) -> dict:
    work = _work_dir(plan_id)
    plan = load_learning_plan(work)
    progress = recompute_progress(plan, load_progress(work))
    if not progress.midterm_unlocked:
        raise HTTPException(status_code=403, detail="交接期中查核尚未解鎖（學習進度需達 50%）")
    bank = load_quiz_bank(work)
    attempt_status = _quiz_attempt_status(progress, "midterm")
    return {
        "scope": "midterm",
        "review_mode": attempt_status == "passed",
        "attempt_status": attempt_status,
        "items": _public_items(bank.midterm, include_answers=attempt_status == "passed"),
    }


@router.get("/{plan_id}/quizzes/final")
def get_final(plan_id: str) -> dict:
    work = _work_dir(plan_id)
    plan = load_learning_plan(work)
    progress = recompute_progress(plan, load_progress(work))
    if not progress.final_unlocked:
        raise HTTPException(
            status_code=403, detail="上手驗收尚未解鎖（需通過全部每日查核）"
        )
    bank = load_quiz_bank(work)
    attempt_status = _quiz_attempt_status(progress, "final")
    return {
        "scope": "final",
        "review_mode": attempt_status == "passed",
        "attempt_status": attempt_status,
        "items": _public_items(bank.final, include_answers=attempt_status == "passed"),
    }


@router.post("/{plan_id}/quizzes/submit")
def submit_quiz(plan_id: str, body: QuizSubmitRequest) -> dict:
    work = _work_dir(plan_id)
    plan = load_learning_plan(work)
    bank = load_quiz_bank(work)
    progress = recompute_progress(plan, load_progress(work))

    if body.scope == "day":
        if body.day is None:
            raise HTTPException(status_code=400, detail="day 必填")
        items = _day_quiz_items(bank, body.day)
        # 每日查核一律需要全對；不受舊 learning_plan.json 的 pass_score 影響。
        pass_score = 1.0
        quiz_key = f"day:{body.day}"
    elif body.scope == "midterm":
        if not progress.midterm_unlocked:
            raise HTTPException(status_code=403, detail="交接期中查核尚未解鎖")
        items = bank.midterm
        pass_score = 0.6
        quiz_key = "midterm"
    elif body.scope == "final":
        if not progress.final_unlocked:
            raise HTTPException(status_code=403, detail="上手驗收尚未解鎖")
        items = bank.final
        pass_score = 0.6
        quiz_key = "final"
    else:
        raise HTTPException(status_code=400, detail="scope 無效")

    result = _grade(items, body.answers, pass_score)
    progress.quiz_attempts.append(
        QuizAttempt(
            quiz_key=quiz_key,
            score=result["score"],
            passed=result["passed"],
            at=datetime.now(timezone.utc).isoformat(),
        )
    )
    if body.scope == "day" and body.day is not None:
        key = str(body.day)
        progress.day_status[key] = (
            DayProgressStatus.passed if result["passed"] else DayProgressStatus.failed
        )
    progress = recompute_progress(plan, progress)
    save_progress(work, progress)
    return {"result": result, "progress": progress.model_dump()}


@router.post("/{plan_id}/assistant", response_model=AssistantAskResponse)
def post_assistant(plan_id: str, body: AssistantAskRequest) -> AssistantAskResponse:
    work = _work_dir(plan_id)
    plan = load_learning_plan(work)
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="問題不可為空")
    if len(question) > MAX_QUESTION_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"問題請控制在 {MAX_QUESTION_CHARS} 字以內",
        )
    if body.day is not None and (body.day < 1 or body.day > plan.days):
        raise HTTPException(status_code=404, detail="天數不存在")
    if not _assistant_limiter.allow(plan_id):
        wait = _assistant_limiter.retry_after_seconds(plan_id)
        raise HTTPException(
            status_code=429,
            detail=f"提問太頻繁，請約 {wait} 秒後再試",
            headers={"Retry-After": str(wait)},
        )
    try:
        result = ask_assistant(work, question, day=body.day)
    except AssistantRequestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("assistant GraphRAG failed after rebuild: %s", plan_id)
        raise HTTPException(
            status_code=500,
            detail="小助手索引建立失敗，已嘗試自動重建，請稍後再試",
        ) from exc
    return AssistantAskResponse(
        answer=result["answer"],
        mode=result.get("mode", "local"),
        engine=result.get("engine", "nano-graphrag"),
        citations=result.get("citations") or [],
        day=body.day,
    )
