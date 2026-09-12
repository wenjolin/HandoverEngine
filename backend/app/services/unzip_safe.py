"""Safe ZIP extraction with traversal and size limits."""

from __future__ import annotations

import zipfile
from pathlib import Path


def safe_extract_zip(
    zip_path: Path,
    dest: Path,
    *,
    max_files: int,
    max_bytes: int,
) -> list[Path]:
    dest = dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)

    extracted: list[Path] = []
    total_bytes = 0

    with zipfile.ZipFile(zip_path, "r") as zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if len(infos) > max_files:
            raise ValueError(f"ZIP 檔案數超過上限（{max_files}）")

        for info in infos:
            name = info.filename.replace("\\", "/")
            if name.startswith("/") or name.startswith("\\"):
                raise ValueError("ZIP 路徑不安全：絕對路徑")
            # Reject path traversal
            target = (dest / name).resolve()
            try:
                target.relative_to(dest)
            except ValueError as exc:
                raise ValueError("ZIP 路徑不安全：偵測到 path traversal") from exc
            if ".." in Path(name).parts:
                raise ValueError("ZIP 路徑不安全：偵測到 path traversal")

            total_bytes += info.file_size
            if total_bytes > max_bytes:
                raise ValueError(f"ZIP 解壓後總大小超過上限（{max_bytes} bytes）")

            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info, "r") as src, open(target, "wb") as out:
                out.write(src.read())
            extracted.append(target)

    return extracted
