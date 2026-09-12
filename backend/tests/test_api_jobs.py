import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import jobs as jobs_api
from app.config import Settings
from app.main import app
from app.models.enums import JobStatus
from app.pipeline.runner import run_job


@pytest.fixture()
def sample_zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("README.md", "# Demo\n\n啟動：python src/app.py\n")
        zf.writestr("src/app.py", "print('hello')\n")
    return buf.getvalue()


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sample_zip_bytes: bytes):
    settings = Settings(
        data_dir=tmp_path / "data",
        use_fake_llm=True,
        embedding_backend="fake",
        max_upload_bytes=200 * 1024 * 1024,
        max_extract_files=5000,
        max_extract_bytes=500 * 1024 * 1024,
    )
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    repo = jobs_api.init_jobs_api(settings)
    monkeypatch.setattr(jobs_api, "get_settings", lambda: settings)
    monkeypatch.setattr("app.pipeline.graph.get_settings", lambda: settings)
    monkeypatch.setattr("app.pipeline.runner.get_settings", lambda: settings, raising=False)

    with TestClient(app) as c:
        # re-bind after lifespan may have run with default settings
        jobs_api.init_jobs_api(settings)
        yield c


def test_create_job_rejects_non_zip(client: TestClient):
    r = client.post("/api/jobs", files={"file": ("a.txt", b"x", "text/plain")})
    assert r.status_code == 400


def test_create_and_poll_with_fake_llm(client: TestClient, sample_zip_bytes: bytes):
    r = client.post(
        "/api/jobs",
        files={"file": ("proj.zip", sample_zip_bytes, "application/zip")},
        data={"days": "7"},
    )
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    status = client.get(f"/api/jobs/{job_id}")
    assert status.status_code == 200
    body = status.json()
    assert body["status"] in {s.value for s in JobStatus}
    # BackgroundTasks run before response returns in TestClient
    assert body["status"] in ("done", "failed") or body["status"] == "queued"
    # If still queued (async oddity), run manually
    if body["status"] != "done":
        settings = jobs_api.get_app_settings()
        repo = jobs_api.get_repo()
        try:
            run_job(job_id, settings=settings, repo=repo)
        except Exception:
            job = repo.get(job_id)
            pytest.fail(f"job failed: {job.error if job else 'missing'}")
        body = client.get(f"/api/jobs/{job_id}").json()

    assert body["status"] == "done", body
    d = client.get(f"/api/jobs/{job_id}/download")
    assert d.status_code == 200
    assert d.headers["content-type"].startswith("application/zip")
    pdf = client.get(f"/api/jobs/{job_id}/download/pdf")
    assert pdf.status_code == 200
    assert pdf.content[:4] == b"%PDF"
