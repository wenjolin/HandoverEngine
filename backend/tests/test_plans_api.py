import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import jobs as jobs_api
from app.config import Settings
from app.main import app
from app.pipeline.runner import run_job


@pytest.fixture()
def sample_zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("README.md", "# Demo\n\n啟動：python src/app.py\n")
        zf.writestr("src/app.py", "print('hello')\n")
    return buf.getvalue()


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
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

    with TestClient(app) as c:
        monkeypatch.setattr(jobs_api, "_repo", repo)
        monkeypatch.setattr(jobs_api, "_settings", settings)
        yield c, settings, repo


def test_plans_day_quiz_and_progress(client, sample_zip_bytes):
    c, settings, repo = client
    files = {"file": ("demo.zip", sample_zip_bytes, "application/zip")}
    r = c.post("/api/jobs", data={"days": "5"}, files=files)
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    run_job(job_id, settings=settings, repo=repo)

    plan = c.get(f"/api/plans/{job_id}")
    assert plan.status_code == 200
    body = plan.json()
    assert body["plan"]["days"] == 5
    assert body["progress"]["percent_complete"] == 0

    day = c.get(f"/api/plans/{job_id}/days/2")
    assert day.status_code == 200
    assert day.json()["day"]["day"] == 2
    assert day.json()["progress"]["day_status"]["2"] == "reading"
    assert day.json()["notes_pdf"].endswith("/days/2/notes.pdf")

    notes = c.get(f"/api/plans/{job_id}/days/2/notes.pdf")
    assert notes.status_code == 200
    assert notes.headers["content-type"].startswith("application/pdf")
    assert notes.content[:4] == b"%PDF"

    quiz = c.get(f"/api/plans/{job_id}/quizzes/day/2")
    assert quiz.status_code == 200
    items = quiz.json()["items"]
    assert len(items) >= 3
    assert "answer" not in items[0]

    answers = {q["id"]: q["choices"][0] for q in items}
    # FakeLLM answer is always 正確敘述 which is choices[0]
    sub = c.post(
        f"/api/plans/{job_id}/quizzes/submit",
        json={"scope": "day", "day": 2, "answers": answers},
    )
    assert sub.status_code == 200
    out = sub.json()
    assert out["result"]["passed"] is True
    assert out["progress"]["day_status"]["2"] == "passed"
    assert out["progress"]["percent_complete"] > 0

    gaps = c.get(f"/api/plans/{job_id}/gaps")
    assert gaps.status_code == 200
    gbody = gaps.json()
    assert "gaps" in gbody
    assert "summary" in gbody
    assert isinstance(gbody["gaps"], list)
    assert set(gbody["summary"]) == {
        "total",
        "coverage",
        "structure",
        "contradiction",
        "manual",
    }
    if gbody["gaps"]:
        assert gbody["gaps"][0].get("question")
        assert gbody["gaps"][0]["status"] == "unresolved"
        assert gbody["gaps"][0]["source_type"] == "auto"



def test_submit_accepts_letter_answer(client, sample_zip_bytes):
    c, settings, repo = client
    files = {"file": ("demo.zip", sample_zip_bytes, "application/zip")}
    r = c.post("/api/jobs", data={"days": "3"}, files=files)
    job_id = r.json()["job_id"]
    run_job(job_id, settings=settings, repo=repo)

    quiz = c.get(f"/api/plans/{job_id}/quizzes/day/1").json()["items"]
    # send letter A for each mcq (canonical first choice)
    answers = {q["id"]: "A" for q in quiz}
    sub = c.post(
        f"/api/plans/{job_id}/quizzes/submit",
        json={"scope": "day", "day": 1, "answers": answers},
    )
    assert sub.status_code == 200
    assert sub.json()["result"]["passed"] is True


def test_gap_management_and_export(client, sample_zip_bytes):
    c, settings, repo = client
    r = c.post("/api/jobs", data={"days": "3"}, files={"file": ("demo.zip", sample_zip_bytes, "application/zip")})
    job_id = r.json()["job_id"]
    run_job(job_id, settings=settings, repo=repo)

    before = c.get(f"/api/plans/{job_id}/gaps").json()
    before_total = before["summary"]["total"]
    before_manual = before["summary"].get("manual", 0)

    created = c.post(f"/api/plans/{job_id}/gaps", json={"title": "需確認部署方式", "question": "正式部署要執行哪些步驟？"})
    assert created.status_code == 201
    report = created.json()
    manual = next(g for g in report["gaps"] if g["kind"] == "manual")
    assert manual["status"] == "unresolved"
    assert report["summary"]["total"] == before_total + 1
    assert report["summary"]["manual"] == before_manual + 1

    work_dir = Path(repo.get(job_id).work_dir)
    persisted_after_create = json.loads((work_dir / "artifacts" / "handover_gaps.json").read_text(encoding="utf-8"))
    assert next(g for g in persisted_after_create["gaps"] if g["id"] == manual["id"])["source_type"] == "manual"

    updated = c.patch(f"/api/plans/{job_id}/gaps/{manual['id']}", json={"status": "resolved"})
    assert updated.status_code == 200
    assert next(g for g in updated.json()["gaps"] if g["id"] == manual["id"])["status"] == "resolved"
    persisted_after_update = json.loads((work_dir / "artifacts" / "handover_gaps.json").read_text(encoding="utf-8"))
    assert next(g for g in persisted_after_update["gaps"] if g["id"] == manual["id"])["status"] == "resolved"

    missing = c.patch(f"/api/plans/{job_id}/gaps/missing-gap", json={"status": "resolved"})
    assert missing.status_code == 404

    exported = c.get(f"/api/plans/{job_id}/gaps/export?status=unresolved")
    assert exported.status_code == 200
    assert "text/plain" in exported.headers["content-type"]
    assert "handover-gaps-questions.txt" in exported.headers["content-disposition"]
    assert "需確認部署方式" not in exported.text

    all_exported = c.get(f"/api/plans/{job_id}/gaps/export?status=all")
    assert all_exported.status_code == 200
    assert "需確認部署方式" in all_exported.text

    exported_pdf = c.get(f"/api/plans/{job_id}/gaps/export/pdf?status=all")
    assert exported_pdf.status_code == 200
    assert exported_pdf.headers["content-type"].startswith("application/pdf")
    assert "handover-gaps-questions.pdf" in exported_pdf.headers["content-disposition"]
    assert exported_pdf.content.startswith(b"%PDF")
    assert len(exported_pdf.content) > 800


def test_assistant_fake_mode(client, sample_zip_bytes, monkeypatch):
    c, settings, repo = client
    monkeypatch.setattr("app.services.learning.assistant.get_settings", lambda: settings)
    files = {"file": ("demo.zip", sample_zip_bytes, "application/zip")}
    r = c.post("/api/jobs", data={"days": "3"}, files=files)
    job_id = r.json()["job_id"]
    run_job(job_id, settings=settings, repo=repo)

    ask = c.post(
        f"/api/plans/{job_id}/assistant",
        json={"question": "這個專案怎麼啟動？", "day": 1},
    )
    assert ask.status_code == 200
    body = ask.json()
    assert body["engine"] == "fake"
    assert "啟動" in body["answer"] or "Fake" in body["answer"] or "關於" in body["answer"]
    assert body["mode"] == "local"

    bad = c.post(
        f"/api/plans/{job_id}/assistant",
        json={"question": "   "},
    )
    assert bad.status_code == 400

    too_long = c.post(
        f"/api/plans/{job_id}/assistant",
        json={"question": "啊" * 201},
    )
    assert too_long.status_code == 422 or too_long.status_code == 400


def test_assistant_rate_limit(client, sample_zip_bytes, monkeypatch):
    c, settings, repo = client
    monkeypatch.setattr("app.services.learning.assistant.get_settings", lambda: settings)
    from app.api import plans as plans_api
    from app.services.rate_limit import SlidingWindowRateLimiter

    monkeypatch.setattr(
        plans_api,
        "_assistant_limiter",
        SlidingWindowRateLimiter(max_calls=3, window_seconds=60.0),
    )
    files = {"file": ("demo.zip", sample_zip_bytes, "application/zip")}
    r = c.post("/api/jobs", data={"days": "3"}, files=files)
    job_id = r.json()["job_id"]
    run_job(job_id, settings=settings, repo=repo)

    for _ in range(3):
        ok = c.post(
            f"/api/plans/{job_id}/assistant",
            json={"question": "入口在哪？"},
        )
        assert ok.status_code == 200
    limited = c.post(
        f"/api/plans/{job_id}/assistant",
        json={"question": "再問一次"},
    )
    assert limited.status_code == 429
