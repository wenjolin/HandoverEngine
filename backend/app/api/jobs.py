"""Jobs API: upload ZIP, poll status, download pack/PDF."""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.config import Settings, get_settings
from app.db.jobs_repo import JobsRepo
from app.db.sqlite import init_db
from app.models.enums import JobStatus
from app.models.schemas import JobOptions, JobPublic
from app.pipeline.nodes.export_pdf import run_export_pdf
from app.pipeline.runner import run_job
from app.services.learning.pdf_export import pdf_looks_ok

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

_repo: JobsRepo | None = None
_settings: Settings | None = None


def init_jobs_api(settings: Settings | None = None) -> JobsRepo:
    global _repo, _settings
    _settings = settings or get_settings()
    _settings.data_dir.mkdir(parents=True, exist_ok=True)
    db_path = _settings.data_dir / "jobs.sqlite"
    init_db(db_path)
    _repo = JobsRepo(db_path)
    return _repo


def get_repo() -> JobsRepo:
    if _repo is None:
        return init_jobs_api()
    return _repo


def get_app_settings() -> Settings:
    if _settings is None:
        return get_settings()
    return _settings


@router.post("")
async def create_job(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    days: int = Form(default=7),
) -> dict:
    settings = get_app_settings()
    repo = get_repo()

    filename = file.filename or ""
    if not filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="僅接受 .zip 檔案")

    data = await file.read()
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(status_code=400, detail="上傳檔案超過大小上限")

    job_id = str(uuid.uuid4())
    work_dir = settings.data_dir / "jobs" / job_id
    work_dir.mkdir(parents=True, exist_ok=True)
    zip_path = work_dir / "input.zip"
    zip_path.write_bytes(data)

    options = JobOptions(days=days, language="zh-TW")
    job = repo.create(
        work_dir=work_dir,
        options=options,
        input_zip_path=zip_path,
        job_id=job_id,
    )
    background_tasks.add_task(run_job, job.id, settings=settings, repo=repo)
    return {"job_id": job.id}


@router.get("/{job_id}")
def get_job(job_id: str) -> JobPublic:
    job = get_repo().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="找不到 Job")
    return JobPublic.from_record(job)


@router.get("/{job_id}/download")
def download_zip(job_id: str) -> FileResponse:
    job = get_repo().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="找不到 Job")
    if job.status != JobStatus.done or not job.output_zip_path or not job.output_zip_path.is_file():
        raise HTTPException(status_code=409, detail="Job 尚未完成或 zip 不存在")
    return FileResponse(
        path=job.output_zip_path,
        filename="handover-pack.zip",
        media_type="application/zip",
    )


@router.get("/{job_id}/download/pdf")
def download_pdf(job_id: str) -> FileResponse:
    job = get_repo().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="找不到 Job")
    if job.status != JobStatus.done:
        raise HTTPException(status_code=409, detail="Job 尚未完成或 PDF 不存在")
    work = Path(job.work_dir)
    pdf_path = work / "artifacts" / "handover-pack.pdf"
    try:
        if not pdf_looks_ok(pdf_path):
            pdf_path = run_export_pdf(work)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"產生 PDF 失敗：{exc}") from exc
    if not pdf_path.is_file():
        raise HTTPException(status_code=409, detail="Job 尚未完成或 PDF 不存在")
    return FileResponse(
        path=pdf_path,
        filename="handover-pack.pdf",
        media_type="application/pdf",
    )
