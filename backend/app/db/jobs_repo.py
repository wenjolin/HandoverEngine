import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.models.enums import JobStatus
from app.models.schemas import JobOptions, JobProgress, JobRecord


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _dt_to_str(dt: datetime) -> str:
    return dt.isoformat()


def _str_to_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


class JobsRepo:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def create(
        self,
        work_dir: Path,
        options: JobOptions,
        input_zip_path: Path | None = None,
        job_id: str | None = None,
    ) -> JobRecord:
        now = _utc_now()
        job_id = job_id or str(uuid.uuid4())
        progress = JobProgress(step=JobStatus.queued.value, percent=0)
        record = JobRecord(
            id=job_id,
            status=JobStatus.queued,
            created_at=now,
            updated_at=now,
            input_zip_path=input_zip_path,
            work_dir=work_dir,
            options=options,
            progress=progress,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    id, status, created_at, updated_at,
                    input_zip_path, work_dir, output_zip_path, output_pdf_path,
                    options, progress, error, stats
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.status.value,
                    _dt_to_str(record.created_at),
                    _dt_to_str(record.updated_at),
                    str(record.input_zip_path) if record.input_zip_path else None,
                    str(record.work_dir),
                    None,
                    None,
                    record.options.model_dump_json(),
                    record.progress.model_dump_json(),
                    None,
                    None,
                ),
            )
            conn.commit()
        return record

    def get(self, job_id: str) -> JobRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def _require_job(self, job_id: str) -> JobRecord:
        job = self.get(job_id)
        if job is None:
            raise KeyError(f"Job not found: {job_id}")
        return job

    def _row_to_record(self, row: sqlite3.Row) -> JobRecord:
        return JobRecord(
            id=row["id"],
            status=JobStatus(row["status"]),
            created_at=_str_to_dt(row["created_at"]),
            updated_at=_str_to_dt(row["updated_at"]),
            input_zip_path=Path(row["input_zip_path"]) if row["input_zip_path"] else None,
            work_dir=Path(row["work_dir"]),
            output_zip_path=Path(row["output_zip_path"]) if row["output_zip_path"] else None,
            output_pdf_path=Path(row["output_pdf_path"]) if row["output_pdf_path"] else None,
            options=JobOptions.model_validate_json(row["options"]),
            progress=JobProgress.model_validate_json(row["progress"]),
            error=row["error"],
        )

    def update_status(
        self,
        job_id: str,
        status: JobStatus,
        message: str | None = None,
        percent: int | None = None,
    ) -> None:
        job = self._require_job(job_id)
        progress = JobProgress(
            step=status.value,
            percent=percent if percent is not None else job.progress.percent,
            message=message if message is not None else job.progress.message,
        )
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status = ?, updated_at = ?, progress = ?
                WHERE id = ?
                """,
                (
                    status.value,
                    _dt_to_str(now),
                    progress.model_dump_json(),
                    job_id,
                ),
            )
            conn.commit()

    def mark_failed(self, job_id: str, error: str) -> None:
        job = self._require_job(job_id)
        progress = JobProgress(
            step=JobStatus.failed.value,
            percent=job.progress.percent,
            message=error,
        )
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status = ?, updated_at = ?, error = ?, progress = ?
                WHERE id = ?
                """,
                (
                    JobStatus.failed.value,
                    _dt_to_str(now),
                    error,
                    progress.model_dump_json(),
                    job_id,
                ),
            )
            conn.commit()

    def mark_done(
        self,
        job_id: str,
        output_zip_path: Path,
        output_pdf_path: Path,
    ) -> None:
        self._require_job(job_id)
        progress = JobProgress(step=JobStatus.done.value, percent=100)
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status = ?, updated_at = ?, progress = ?,
                    output_zip_path = ?, output_pdf_path = ?
                WHERE id = ?
                """,
                (
                    JobStatus.done.value,
                    _dt_to_str(now),
                    progress.model_dump_json(),
                    str(output_zip_path),
                    str(output_pdf_path),
                    job_id,
                ),
            )
            conn.commit()
