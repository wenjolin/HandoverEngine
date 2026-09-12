from pathlib import Path
from types import SimpleNamespace

from app.services.indexing.chunking import chunk_file
from app.services.indexing.chroma_store import ChromaStore, iter_embedding_batches


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


def test_chunk_single_very_long_line_never_exceeds_budget(tmp_path: Path):
    p = tmp_path / "minified.js"
    p.write_text("x" * 2_000, encoding="utf-8")

    chunks = chunk_file(p, "minified.js", max_chars=120, overlap=20)

    assert len(chunks) >= 2
    assert all(len(chunk["text"]) <= 120 for chunk in chunks)
    assert all(chunk["start_line"] == 1 and chunk["end_line"] == 1 for chunk in chunks)


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


def test_embedding_batches_stay_within_safe_request_budget():
    texts = ["x" * 1_000 for _ in range(130)]

    batches = list(iter_embedding_batches(texts))

    assert [len(batch) for batch in batches] == [50, 50, 30]
    assert [item for batch in batches for item in batch] == texts
    assert all(sum(len(item) for item in batch) <= 50_000 for batch in batches)


def test_openai_embeddings_are_sent_in_multiple_safe_batches(tmp_path: Path, monkeypatch):
    calls: list[list[str]] = []

    class FakeEmbeddings:
        def create(self, *, model, input):
            calls.append(input)
            return SimpleNamespace(
                data=[
                    SimpleNamespace(index=index, embedding=[float(index)])
                    for index, _ in enumerate(input)
                ]
            )

    fake_client = SimpleNamespace(embeddings=FakeEmbeddings())
    monkeypatch.setattr(
        "app.services.indexing.chroma_store.OpenAI", lambda **_: fake_client
    )
    store = ChromaStore(
        tmp_path / "idx",
        embedding_backend="openai",
        openai_api_key="test-key",
    )

    vectors = store.embed_texts(["x" * 1_000 for _ in range(130)])

    assert [len(batch) for batch in calls] == [50, 50, 30]
    assert len(vectors) == 130
