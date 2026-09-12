"""Assistant index prebuild after job completion."""

from __future__ import annotations

import zipfile
from pathlib import Path

from app.config import Settings
from app.db.jobs_repo import JobsRepo
from app.db.sqlite import init_db
from app.models.enums import JobStatus
from app.models.schemas import JobOptions
from app.pipeline.runner import run_job
from app.services.learning.assistant import prebuild_assistant_index, ready_marker


def test_run_job_prebuilds_assistant_marker(tmp_path: Path, monkeypatch):
    settings = Settings(
        data_dir=tmp_path / "data",
        use_fake_llm=True,
        embedding_backend="fake",
        max_extract_files=100,
        max_extract_bytes=10_000_000,
    )
    settings.data_dir.mkdir(parents=True)
    monkeypatch.setattr("app.pipeline.graph.get_settings", lambda: settings)
    # 背景預建改同步，避免測試競態
    monkeypatch.setattr(
        "app.pipeline.runner.schedule_assistant_background",
        lambda work_dir, s: prebuild_assistant_index(work_dir, s),
    )

    db = settings.data_dir / "jobs.sqlite"
    init_db(db)
    repo = JobsRepo(db)

    work = settings.data_dir / "jobs" / "prebuild1"
    work.mkdir(parents=True)
    with zipfile.ZipFile(work / "input.zip", "w") as zf:
        zf.writestr("README.md", "# Prebuild\n")
        zf.writestr("src/app.py", "print(1)\n")

    job = repo.create(
        work_dir=work,
        options=JobOptions(days=3),
        input_zip_path=work / "input.zip",
    )
    run_job(job.id, settings=settings, repo=repo)
    got = repo.get(job.id)
    assert got is not None
    assert got.status == JobStatus.done
    assert ready_marker(work).is_file()
    assert "小助手" in (got.progress.message or "")
