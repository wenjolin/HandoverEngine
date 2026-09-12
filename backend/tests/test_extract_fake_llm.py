import json
import zipfile
from pathlib import Path

from app.config import Settings
from app.pipeline.llm import FakeLLMClient
from app.pipeline.nodes.extract import run_extract
from app.pipeline.nodes.ingest import run_ingest
from app.pipeline.nodes.index import run_index


def test_extract_writes_cards_json(tmp_path: Path):
    z = tmp_path / "input.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("README.md", "# Sample\n啟動方式\n")
        zf.writestr("src/app.py", "print('hi')\n")
    work = tmp_path / "job"
    work.mkdir()
    z.rename(work / "input.zip")

    settings = Settings(
        use_fake_llm=True,
        embedding_backend="fake",
        max_extract_files=100,
        max_extract_bytes=10_000_000,
    )
    run_ingest(work, settings)
    run_index(work, settings)

    cards = run_extract(work, settings, FakeLLMClient())
    assert (work / "artifacts" / "cards.json").exists()
    assert (work / "artifacts" / "coverage.json").exists()
    assert len(cards) >= 1
    raw = json.loads((work / "artifacts" / "cards.json").read_text(encoding="utf-8"))
    assert "cards" in raw
    assert "coverage" in raw
    # citations should prefer chunk_id when present
    cite = raw["cards"][0]["citations"][0]
    assert "path" in cite
