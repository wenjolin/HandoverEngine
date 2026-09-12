"""Index node: chunk analyzable files and build per-job vector store."""

from __future__ import annotations

import json
from pathlib import Path

from app.config import Settings
from app.services.indexing.chunking import chunk_file
from app.services.indexing.chroma_store import ChromaStore
from app.services.secrets_filter import is_ignored_path, is_secret_path

_MAX_FILE_BYTES = 1_000_000


def run_index(work_dir: Path, settings: Settings) -> dict:
    raw = work_dir / "raw"
    artifacts = work_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    tree_path = artifacts / "file_tree.json"
    if not tree_path.is_file():
        raise ValueError("缺少 file_tree.json，請先執行 ingest")

    tree = json.loads(tree_path.read_text(encoding="utf-8"))
    analyzable = tree.get("analyzable_paths") or tree.get("paths") or []

    store = ChromaStore(
        work_dir / "index",
        embedding_backend=settings.embedding_backend,
        openai_api_key=settings.embedding_api_key or settings.openai_api_key,
        openai_base_url=settings.embedding_base_url or settings.openai_base_url,
        embedding_model=settings.embedding_model,
    )

    all_chunks: list[dict] = []
    files_meta: list[dict] = []
    for rel in analyzable:
        if is_ignored_path(rel) or is_secret_path(rel):
            continue
        path = raw / rel
        if not path.is_file():
            continue
        size = path.stat().st_size
        if size > _MAX_FILE_BYTES:
            files_meta.append({"path": rel, "skipped": True, "reason": "too_large"})
            continue
        chunks = chunk_file(path, rel)
        all_chunks.extend(chunks)
        files_meta.append({"path": rel, "chunk_count": len(chunks), "skipped": False})

    store.add_chunks(all_chunks)
    (artifacts / "files.json").write_text(
        json.dumps({"files": files_meta, "chunk_count": len(all_chunks)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"file_count": len(files_meta), "chunk_count": len(all_chunks)}
