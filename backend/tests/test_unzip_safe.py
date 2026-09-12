import zipfile
from pathlib import Path

import pytest

from app.services.unzip_safe import safe_extract_zip


def test_rejects_path_traversal(tmp_path: Path):
    z = tmp_path / "bad.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("../evil.txt", "x")
    with pytest.raises(ValueError, match="traversal|不安全"):
        safe_extract_zip(z, tmp_path / "out", max_files=100, max_bytes=10_000_000)


def test_extracts_normal_file(tmp_path: Path):
    z = tmp_path / "ok.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("README.md", "# hi")
    files = safe_extract_zip(z, tmp_path / "out", max_files=100, max_bytes=10_000_000)
    assert any(p.name == "README.md" for p in files)
