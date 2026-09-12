from pathlib import Path

from app.services.indexing.chunking import chunk_file
from app.services.indexing.chroma_store import ChromaStore


def test_chunk_file_assigns_line_ranges(tmp_path: Path):
    p = tmp_path / "a.py"
    p.write_text("\n".join(f"line{i}" for i in range(1, 101)), encoding="utf-8")
    chunks = chunk_file(p, "a.py", max_chars=80, overlap=10)
    assert len(chunks) >= 2
    assert chunks[0]["path"] == "a.py"
    assert chunks[0]["start_line"] >= 1
    assert chunks[0]["module"] == "_root"


def test_chunk_python_splits_on_top_level_defs(tmp_path: Path):
    p = tmp_path / "svc.py"
    p.write_text(
        "\n".join(
            [
                "x = 1",
                "",
                "def alpha():",
                "    return 1",
                "",
                "def beta():",
                "    return 2",
                "",
                "class Gamma:",
                "    def m(self):",
                "        return 3",
            ]
        ),
        encoding="utf-8",
    )
    chunks = chunk_file(p, "app/svc.py", max_chars=2000)
    alpha = next(c for c in chunks if "def alpha" in c["text"])
    beta = next(c for c in chunks if "def beta" in c["text"])
    gamma = next(c for c in chunks if "class Gamma" in c["text"])
    assert alpha["id"] != beta["id"]
    assert "def beta" not in alpha["text"]
    assert "def alpha" not in beta["text"]
    assert "def m(self)" in gamma["text"]
    assert "def alpha" not in gamma["text"]
    assert all(c["module"] == "app" for c in chunks)


def test_chunk_markdown_splits_on_headings(tmp_path: Path):
    p = tmp_path / "README.md"
    p.write_text(
        "# Intro\nhello\n\n## Install\npip install x\n\n## Run\npython main.py\n",
        encoding="utf-8",
    )
    chunks = chunk_file(p, "docs/README.md", max_chars=2000)
    assert len(chunks) >= 2
    assert any("# Intro" in c["text"] for c in chunks)
    assert any("## Install" in c["text"] for c in chunks)
    assert chunks[0]["module"] == "docs"


def test_chunk_oversized_unit_falls_back_to_length(tmp_path: Path):
    p = tmp_path / "big.py"
    body = "\n".join(f"    x{i} = {i}" for i in range(200))
    p.write_text(f"def huge():\n{body}\n", encoding="utf-8")
    chunks = chunk_file(p, "big.py", max_chars=120, overlap=20)
    assert len(chunks) >= 2
    assert all(len(c["text"]) <= 120 + 50 for c in chunks)  # 允許單行略超


def test_chroma_store_query_returns_similar_chunk(tmp_path: Path):
    store = ChromaStore(tmp_path / "idx", embedding_backend="fake")
    store.add_chunks(
        [
            {
                "id": "1",
                "path": "README.md",
                "start_line": 1,
                "end_line": 2,
                "text": "如何用 docker compose 啟動專案",
            },
            {
                "id": "2",
                "path": "x.py",
                "start_line": 1,
                "end_line": 1,
                "text": "print('unrelated')",
            },
        ]
    )
    hits = store.query("docker compose 啟動", k=1)
    assert hits
    assert hits[0]["path"] == "README.md"
