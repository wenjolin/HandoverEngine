"""Run a handover job end-to-end and update JobsRepo status."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from app.config import Settings
from app.db.jobs_repo import JobsRepo
from app.models.enums import JobStatus
from app.pipeline.graph import build_graph
from app.services.learning.assistant import prebuild_assistant_index

logger = logging.getLogger(__name__)


def _bg_assistant(work_dir: Path, settings: Settings) -> None:
    try:
        ok = prebuild_assistant_index(work_dir, settings)
        if ok:
            logger.info("background assistant index ready: %s", work_dir)
        else:
            logger.warning("background assistant prebuild skipped/failed: %s", work_dir)
    except Exception:
        logger.exception("background assistant prebuild failed: %s", work_dir)


def schedule_assistant_background(work_dir: Path, settings: Settings) -> None:
    """Prebuild learning assistant index without blocking job completion."""
    t = threading.Thread(
        target=_bg_assistant,
        args=(work_dir, settings),
        name=f"assistant-{work_dir.name}",
        daemon=True,
    )
    t.start()


def run_job(job_id: str, *, settings: Settings, repo: JobsRepo) -> None:
    job = repo.get(job_id)
    if job is None:
        raise KeyError(f"Job not found: {job_id}")

    work_dir = Path(job.work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    artifacts = work_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "job_options.json").write_text(
        job.options.model_dump_json(),
        encoding="utf-8",
    )

    def on_progress(status: JobStatus, percent: int, message: str) -> None:
        repo.update_status(job_id, status, message=message, percent=percent)

    try:
        graph = build_graph(on_progress=on_progress)
        graph.invoke({"work_dir": str(work_dir)})

        zip_path = work_dir / "handover-pack.zip"
        pdf_path = work_dir / "artifacts" / "handover-pack.pdf"
        if not zip_path.is_file() or not pdf_path.is_file():
            raise RuntimeError("產出檔案不完整")
        repo.mark_done(job_id, output_zip_path=zip_path, output_pdf_path=pdf_path)

        schedule_assistant_background(work_dir, settings)
        repo.update_status(
            job_id,
            JobStatus.done,
            message="學習計畫已就緒（小助手背景建立中）",
            percent=100,
        )
    except Exception as exc:  # noqa: BLE001
        repo.mark_failed(job_id, str(exc))
        raise
