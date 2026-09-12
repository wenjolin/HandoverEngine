"""Markdown → PDF with CJK font support via fpdf2."""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

from fpdf import FPDF

from app.models.schemas import DayPackage
from app.services.learning.store import artifacts_dir, load_day_package


def day_package_to_notes_markdown(pkg: DayPackage) -> str:
    """整理 DayPackage 成可下載的重點筆記 Markdown。"""
    lines = [
        f"# Day {pkg.day} 重點筆記",
        "",
        f"**主題：** {pkg.theme or '（未命名）'}",
        "",
    ]
    for blk in pkg.blocks:
        title = blk.title or (blk.type.value if hasattr(blk.type, "value") else str(blk.type))
        lines.append(f"## {title}")
        lines.append("")
        body = (blk.body or "").strip()
        if body:
            lines.append(body)
            lines.append("")
        if blk.paths:
            lines.append("### 參考路徑")
            lines.append("")
            for p in blk.paths:
                lines.append(f"- `{p}`")
            lines.append("")
    if pkg.source_refs:
        lines.append("## 來源索引")
        lines.append("")
        for p in pkg.source_refs:
            lines.append(f"- `{p}`")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


# kaiu/DFKai-SB embeds with wrong advances in fpdf2 → overlapping glyphs.
_BAD_PDF_FONTS = (b"DFKai-SB", b"KaiTi", "標楷體".encode("utf-8"))
_PDF_LAYOUT_CREATOR = "Handover Learning Pack PDF Layout 2"


@lru_cache(maxsize=1)
def _find_cjk_font() -> tuple[Path, int]:
    """回傳 (字型路徑, TTC face index)。優先選 fpdf2 寬度正常的字型。"""
    env = os.environ.get("HANDOVER_PDF_FONT")
    # (path, collection_font_number)
    candidates: list[tuple[Path, int]] = []
    if env:
        candidates.append((Path(env), int(os.environ.get("HANDOVER_PDF_FONT_INDEX", "0"))))

    windir = os.environ.get("WINDIR", r"C:\Windows")
    fonts = Path(windir) / "Fonts"
    # Prefer Microsoft JhengHei / YaHei — kaiu overlaps under fpdf2.
    candidates.extend(
        [
            (fonts / "msjh.ttc", 0),
            (fonts / "msyh.ttc", 0),
            (fonts / "msjhbd.ttc", 0),
            (fonts / "simsun.ttc", 0),
            (fonts / "mingliu.ttc", 0),
            # Last resort only (known broken metrics with fpdf2):
            (fonts / "kaiu.ttf", 0),
        ]
    )
    candidates.extend(
        [
            (Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"), 0),
            (Path("/System/Library/Fonts/PingFang.ttc"), 0),
            (Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"), 0),
            (Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"), 0),
            (Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"), 0),
        ]
    )
    for path, idx in candidates:
        if path.is_file() and path.stat().st_size > 0:
            return path, idx
    raise FileNotFoundError(
        "找不到可用的中文字型。請安裝微軟正黑體／Noto Sans CJK，"
        "或設定環境變數 HANDOVER_PDF_FONT 指向 .ttf/.ttc"
    )


def _strip_md_inline(text: str) -> str:
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    return text


class _NotesPDF(FPDF):
    def header(self) -> None:
        """Paint an opaque white page so macOS preview never shows a dark canvas."""
        self.set_fill_color(255, 255, 255)
        self.rect(0, 0, self.w, self.h, style="F")

    def footer(self) -> None:
        self.set_y(-15)
        self.set_font(self._cjk_family, size=9)
        self.set_text_color(120, 120, 120)
        self.cell(0, 10, f"{self.page_no()}", align="C")


def _markdown_to_pdf_fpdf(markdown: str, pdf_path: Path, *, title: str) -> Path:
    font_path, font_index = _find_cjk_font()
    family = "cjk"
    pdf = _NotesPDF(format="A4")
    pdf._cjk_family = family  # type: ignore[attr-defined]
    pdf.set_creator(_PDF_LAYOUT_CREATOR)
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.set_margins(left=18, top=18, right=18)
    add_kwargs: dict = {}
    if font_path.suffix.lower() == ".ttc":
        add_kwargs["collection_font_number"] = font_index
    pdf.add_font(family, "", str(font_path), **add_kwargs)
    pdf.add_page()

    def write_line(
        text: str,
        *,
        size: float = 11,
        line_height: float = 7.5,
        color: tuple[int, int, int] = (38, 46, 62),
    ) -> None:
        pdf.set_x(pdf.l_margin)
        pdf.set_font(family, size=size)
        # footer() changes the colour. Reset it for every block after page breaks.
        pdf.set_text_color(*color)
        safe = _strip_md_inline(text)
        if not safe.strip():
            pdf.ln(line_height * 0.35)
            return
        # CJK has no word boundaries and source paths may be long. Character wrapping
        # prevents clipped lines; left alignment avoids FPDF's stretched justification.
        safe = safe.replace("\u2022", "-").replace("\u00b7", "-").replace("\t", "    ")
        pdf.multi_cell(
            0,
            line_height,
            safe,
            align="L",
            max_line_height=line_height,
            new_x="LMARGIN",
            new_y="NEXT",
            wrapmode="CHAR",
        )

    def write_heading(text: str, *, level: int) -> None:
        if level == 1:
            if pdf.will_page_break(15):
                pdf.add_page()
            write_line(text or title, size=18, line_height=11, color=(24, 48, 82))
            pdf.ln(2)
            return
        if pdf.will_page_break(13):
            pdf.add_page()
        pdf.ln(1.5)
        write_line(text, size=14 if level == 2 else 12, line_height=8.5, color=(29, 86, 142))
        pdf.ln(0.5)

    in_code = False
    for raw in markdown.splitlines():
        line = raw.rstrip("\n")
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            write_line(line, size=9.5, line_height=6.5, color=(52, 58, 68))
            continue
        if line.startswith("# "):
            write_heading(line[2:].strip(), level=1)
        elif line.startswith("## "):
            write_heading(line[3:].strip(), level=2)
        elif line.startswith("### "):
            write_heading(line[4:].strip(), level=3)
        elif line.startswith("- "):
            write_line("- " + line[2:].strip(), size=10.5, line_height=7.2)
        elif line.strip() == "":
            pdf.ln(2.5)
        else:
            write_line(line, size=10.5, line_height=7.2)

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(pdf_path))
    return pdf_path


def markdown_text_to_pdf(
    markdown: str,
    pdf_path: Path,
    *,
    title: str = "Notes",
) -> Path:
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    return _markdown_to_pdf_fpdf(markdown, pdf_path, title=title)


def handover_gaps_to_questions_markdown(gaps: list[dict]) -> str:
    """Format handover gaps as a concise, printable question list."""
    kind_labels = {
        "coverage": "覆蓋",
        "structure": "結構",
        "contradiction": "矛盾",
        "manual": "手動新增",
    }
    lines = [f"# 交接缺口問題清單（{len(gaps)} 項）", ""]
    for index, gap in enumerate(gaps, start=1):
        kind = kind_labels.get(str(gap.get("kind") or ""), str(gap.get("kind") or ""))
        lines.extend(
            [
                f"## {index}. [{kind}] {gap.get('title', '')}",
                "",
                f"疑問：{gap.get('question', '')}",
            ]
        )
        if gap.get("detail"):
            lines.append(f"說明：{gap['detail']}")
        if gap.get("sources"):
            lines.append(f"依據：{', '.join(str(p) for p in gap['sources'])}")
        lines.append("")
    return "\n".join(lines)


def export_handover_gaps_pdf(work_dir: Path, gaps: list[dict]) -> Path:
    """Create a downloadable PDF of selected handover-gap questions."""
    path = artifacts_dir(work_dir) / "handover-gaps-questions.pdf"
    return markdown_text_to_pdf(
        handover_gaps_to_questions_markdown(gaps),
        path,
        title="交接缺口問題清單",
    )


def markdown_files_to_pdf(
    md_paths: list[Path],
    pdf_path: Path,
    *,
    title: str = "Handover Learning Pack",
) -> Path:
    chunks: list[str] = [f"# {title}", ""]
    for p in md_paths:
        if not p.is_file():
            continue
        chunks.append(p.read_text(encoding="utf-8"))
        chunks.append("")
        if p.name.startswith("02-"):
            svg = p.parent / "diagrams" / "architecture.svg"
            if svg.is_file():
                chunks.append("## Architecture Diagram")
                chunks.append("")
                chunks.append("見 diagrams/architecture.svg")
                chunks.append("")
    return markdown_text_to_pdf("\n".join(chunks), pdf_path, title=title)


def day_notes_pdf_path(work_dir: Path, day: int) -> Path:
    return work_dir / "artifacts" / "days" / f"{day}-notes.pdf"


def export_day_notes_pdf(work_dir: Path, pkg: DayPackage) -> Path:
    md = day_package_to_notes_markdown(pkg)
    pdf_path = day_notes_pdf_path(work_dir, pkg.day)
    return markdown_text_to_pdf(
        md,
        pdf_path,
        title=f"Day {pkg.day} Notes",
    )


def ensure_day_notes_pdf(work_dir: Path, day: int) -> Path:
    """回傳既有 notes PDF；若缺／舊亂碼／重疊字型檔則由 DayPackage 重產。"""
    pdf_path = day_notes_pdf_path(work_dir, day)
    if pdf_path.is_file() and pdf_looks_ok(pdf_path):
        return pdf_path
    pkg = load_day_package(work_dir, day)
    return export_day_notes_pdf(work_dir, pkg)


def pdf_looks_ok(path: Path) -> bool:
    """粗略判斷：太小、舊 ASCII fallback、或已知會重疊的字型則視為無效。"""
    try:
        data = path.read_bytes()
    except OSError:
        return False
    if len(data) < 800 or not data.startswith(b"%PDF"):
        return False
    if b"/BaseFont /Helvetica" in data and len(data) < 2500:
        return False
    if _PDF_LAYOUT_CREATOR.encode("ascii") not in data:
        return False
    # fpdf2 + DFKai-SB (kaiu) produces overlapping CJK; force regenerate.
    if any(marker in data for marker in _BAD_PDF_FONTS):
        return False
    return True
