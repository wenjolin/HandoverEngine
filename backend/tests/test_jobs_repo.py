from pathlib import Path

import pytest

from app.db.jobs_repo import JobsRepo
from app.db.sqlite import init_db
from app.models.enums import JobStatus
from app.models.schemas import JobOptions


def test_create_and_get_job(tmp_path: Path):
    db = tmp_path / "jobs.sqlite"
    init_db(db)
    repo = JobsRepo(db)
    job = repo.create(work_dir=tmp_path / "j1", options=JobOptions(days=7))
    got = repo.get(job.id)
    assert got is not None
    assert got.status == JobStatus.queued
    assert got.options.days == 7


def test_mark_failed_updates_progress(tmp_path: Path):
    db = tmp_path / "jobs.sqlite"
    init_db(db)
    repo = JobsRepo(db)
    job = repo.create(work_dir=tmp_path / "j1", options=JobOptions(days=7))
    repo.update_status(
        job.id, JobStatus.extracting, percent=42, message="working"
    )
    repo.mark_failed(job.id, "something broke")
    got = repo.get(job.id)
    assert got is not None
    assert got.status == JobStatus.failed
    assert got.error == "something broke"
    assert got.progress.step == JobStatus.failed.value
    assert got.progress.percent == 42
    assert got.progress.message == "something broke"


def test_mutating_methods_raise_on_missing_job_id(tmp_path: Path):
    db = tmp_path / "jobs.sqlite"
    init_db(db)
    repo = JobsRepo(db)
    missing = "00000000-0000-0000-0000-000000000000"

    with pytest.raises(KeyError, match="Job not found"):
        repo.update_status(missing, JobStatus.ingesting)

    with pytest.raises(KeyError, match="Job not found"):
        repo.mark_failed(missing, "err")

    with pytest.raises(KeyError, match="Job not found"):
        repo.mark_done(missing, tmp_path / "out.zip", tmp_path / "out.pdf")
