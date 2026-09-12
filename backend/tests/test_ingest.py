import json
import zipfile
from pathlib import Path

import pytest

from app.config import Settings
from app.pipeline.nodes.ingest import run_ingest


def _make_zip(tmp_path: Path, members: dict[str, str]) -> Path:
    z = tmp_path / "input.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for name, content in members.items():
            zf.writestr(name, content)
    return z


def test_ingest_writes_file_tree_and_skips_ignored(tmp_path: Path):
    z = _make_zip(
        tmp_path,
        {
            "README.md": "# sample",
            "src/app.py": "print('hi')\n",
            "node_modules/pkg/index.js": "ignored",
            ".venv/lib/site.py": "ignored",
            "venv/lib/site.py": "ignored",
            "env/lib/site.py": "ignored",
            ".env": "SECRET=1",
        },
    )
    work = tmp_path / "job"
    work.mkdir()
    z.rename(work / "input.zip")

    settings = Settings(max_extract_files=100, max_extract_bytes=10_000_000)
    result = run_ingest(work, settings)

    tree_path = work / "artifacts" / "file_tree.json"
    assert tree_path.exists()
    tree = json.loads(tree_path.read_text(encoding="utf-8"))
    paths = tree["paths"]
    assert "README.md" in paths
    assert "src/app.py" in paths
    assert not any(p.startswith("node_modules/") for p in paths)
    assert not any(p.startswith(".venv/") for p in paths)
    assert not any(p.startswith("venv/") for p in paths)
    assert not any(p.startswith("env/") for p in paths)
    assert ".env" not in paths
    assert result["file_count"] >= 2


def test_ingest_fails_when_no_analyzable_text(tmp_path: Path):
    z = _make_zip(tmp_path, {"node_modules/x.js": "x"})
    work = tmp_path / "job"
    work.mkdir()
    z.rename(work / "input.zip")
    settings = Settings(max_extract_files=100, max_extract_bytes=10_000_000)
    with pytest.raises(ValueError, match="找不到可分析"):
        run_ingest(work, settings)
