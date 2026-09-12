import json
import zipfile
from pathlib import Path

from app.config import Settings
from app.db.jobs_repo import JobsRepo
from app.db.sqlite import init_db
from app.models.enums import JobStatus
from app.models.schemas import JobOptions
from app.pipeline.runner import run_job


def test_pipeline_e2e_fake(tmp_path: Path, monkeypatch):
    settings = Settings(
        data_dir=tmp_path / "data",
        use_fake_llm=True,
        embedding_backend="fake",
        max_extract_files=100,
        max_extract_bytes=10_000_000,
    )
    settings.data_dir.mkdir(parents=True)
    monkeypatch.setattr("app.pipeline.graph.get_settings", lambda: settings)

    db = settings.data_dir / "jobs.sqlite"
    init_db(db)
    repo = JobsRepo(db)

    work = settings.data_dir / "jobs" / "e2e1"
    work.mkdir(parents=True)
    with zipfile.ZipFile(work / "input.zip", "w") as zf:
        zf.writestr("README.md", "# E2E\n")
        zf.writestr("src/app.py", "print(1)\n")

    job = repo.create(
        work_dir=work,
        options=JobOptions(days=7),
        input_zip_path=work / "input.zip",
    )
    run_job(job.id, settings=settings, repo=repo)
    got = repo.get(job.id)
    assert got is not None
    assert got.status == JobStatus.done
    assert Path(got.output_zip_path).exists()
    assert Path(got.output_pdf_path).exists()
    art = work / "artifacts"
    assert (art / "learning_plan.json").is_file()
    assert (art / "quiz_bank.json").is_file()
    assert (art / "progress.json").is_file()
    assert (art / "handover_gaps.json").is_file()
    assert (art / "days" / "1.json").is_file()
    bank = json.loads((art / "quiz_bank.json").read_text(encoding="utf-8"))
    assert len(bank.get("midterm") or []) >= 10
    assert len(bank.get("final") or []) >= 20
