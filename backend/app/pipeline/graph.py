"""Assemble LangGraph handover pipeline (with validate retry loop)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from langgraph.graph import END, START, StateGraph

from app.config import get_settings
from app.models.enums import JobStatus
from app.models.schemas import JobOptions
from app.pipeline.llm import get_llm_client
from app.pipeline.nodes.day_writer import run_day_writer
from app.pipeline.nodes.export_pdf import run_export_pdf
from app.pipeline.nodes.extract import (
    MAX_COVERAGE_RETRIES,
    decide_coverage_route,
    run_check_coverage,
    run_extract,
    run_extract_gap,
)
from app.pipeline.nodes.handover_gaps import run_handover_gaps
from app.pipeline.nodes.index import run_index
from app.pipeline.nodes.ingest import run_ingest
from app.pipeline.nodes.outline import run_outline
from app.pipeline.nodes.package import run_package
from app.pipeline.nodes.quiz_smith import run_quiz_smith
from app.pipeline.nodes.render_diagrams import run_render_diagrams
from app.pipeline.nodes.validate_curriculum import (
    MAX_REPAIR_RETRIES,
    decide_validate_route,
    run_validate_curriculum,
)
from app.pipeline.repair.agent import run_repair_agent
from app.pipeline.state import HandoverState

ProgressCb = Callable[[JobStatus, int, str], None]


def build_graph(on_progress: ProgressCb | None = None):
    def progress(status: JobStatus, percent: int, message: str) -> None:
        if on_progress:
            on_progress(status, percent, message)

    def load_options(work_dir: Path) -> JobOptions:
        opts_path = work_dir / "artifacts" / "job_options.json"
        if opts_path.is_file():
            return JobOptions.model_validate_json(opts_path.read_text(encoding="utf-8"))
        return JobOptions()

    graph = StateGraph(HandoverState)

    def ingest(state: HandoverState) -> HandoverState:
        progress(JobStatus.ingesting, 10, "正在解壓專案…")
        run_ingest(Path(state["work_dir"]), get_settings())
        return state

    def index(state: HandoverState) -> HandoverState:
        progress(JobStatus.indexing, 25, "正在建立索引…")
        run_index(Path(state["work_dir"]), get_settings())
        return state

    def extract(state: HandoverState) -> HandoverState:
        progress(JobStatus.extracting, 45, "正在萃取知識…")
        settings = get_settings()
        run_extract(Path(state["work_dir"]), settings, get_llm_client(settings))
        return state

    def check_coverage(state: HandoverState) -> HandoverState:
        progress(JobStatus.extracting, 48, "正在檢查知識覆蓋…")
        result = run_check_coverage(Path(state["work_dir"]))
        retries = int(state.get("coverage_retries") or 0)
        route = decide_coverage_route(
            coverage_ok=result.ok,
            uncovered_paths=result.uncovered_paths,
            coverage_retries=retries,
        )
        out: HandoverState = {
            **state,
            "coverage_ok": result.ok,
            "uncovered_paths": result.uncovered_paths,
            "coverage_route": route,
        }
        if route == "extract_gap":
            out["coverage_retries"] = retries + 1
            progress(
                JobStatus.extracting,
                50,
                f"覆蓋不足，補抽缺口（{out['coverage_retries']}/{MAX_COVERAGE_RETRIES}）…",
            )
        return out

    def extract_gap(state: HandoverState) -> HandoverState:
        progress(JobStatus.extracting, 52, "正在補抽未覆蓋檔案…")
        settings = get_settings()
        run_extract_gap(
            Path(state["work_dir"]),
            settings,
            get_llm_client(settings),
            list(state.get("uncovered_paths") or []),
        )
        return state

    def handover_gaps(state: HandoverState) -> HandoverState:
        progress(JobStatus.extracting, 54, "正在分析交接缺口…")
        settings = get_settings()
        run_handover_gaps(Path(state["work_dir"]), get_llm_client(settings))
        return state

    def outline(state: HandoverState) -> HandoverState:
        progress(JobStatus.planning, 55, "正在產生學習大綱…")
        settings = get_settings()
        work = Path(state["work_dir"])
        run_outline(work, load_options(work), get_llm_client(settings))
        return state

    def day_writer(state: HandoverState) -> HandoverState:
        progress(JobStatus.curriculum, 68, "正在撰寫每日教材…")
        settings = get_settings()
        work = Path(state["work_dir"])
        run_day_writer(work, load_options(work), get_llm_client(settings))
        return state

    def quiz_smith(state: HandoverState) -> HandoverState:
        progress(JobStatus.writing_quizzes, 78, "正在出題…")
        settings = get_settings()
        work = Path(state["work_dir"])
        run_quiz_smith(work, load_options(work), get_llm_client(settings))
        return state

    def validate(state: HandoverState) -> HandoverState:
        progress(JobStatus.validating, 84, "正在驗證課綱…")
        work = Path(state["work_dir"])
        result = run_validate_curriculum(work, load_options(work))
        repair_retries = int(state.get("repair_retries") or 0)
        route = decide_validate_route(
            validate_ok=result.ok,
            issues=result.issues,
            repair_retries=repair_retries,
        )
        out: HandoverState = {
            **state,
            "validate_ok": result.ok,
            "validate_issues": result.issues,
            "validate_warnings": result.warnings,
            "validate_route": route,
        }
        if route == "repair":
            out["repair_retries"] = repair_retries + 1
            progress(
                JobStatus.validating,
                85,
                f"驗證未過，啟動修復代理人（{out['repair_retries']}/{MAX_REPAIR_RETRIES}）…",
            )
        return out

    def repair(state: HandoverState) -> HandoverState:
        progress(JobStatus.validating, 86, "修復代理人執行工具中…")
        settings = get_settings()
        work = Path(state["work_dir"])
        result = run_repair_agent(
            work,
            load_options(work),
            get_llm_client(settings),
            settings,
            issues=list(state.get("validate_issues") or []),
        )
        return {
            **state,
            "validate_ok": result.ok,
            "validate_issues": result.issues,
            "repair_steps": result.steps,
        }

    def fail_validate(state: HandoverState) -> HandoverState:
        issues = state.get("validate_issues") or []
        detail = "; ".join(
            str(i.get("message") or i.get("code") or "") for i in issues
        )
        raise ValueError(f"課綱驗證重試耗盡：{detail or 'unknown'}")

    def render(state: HandoverState) -> HandoverState:
        progress(JobStatus.rendering, 88, "正在渲染架構圖…")
        run_render_diagrams(Path(state["work_dir"]))
        return state

    def export_pdf(state: HandoverState) -> HandoverState:
        progress(JobStatus.exporting_pdf, 93, "正在產生 PDF…")
        run_export_pdf(Path(state["work_dir"]))
        return state

    def package(state: HandoverState) -> HandoverState:
        progress(JobStatus.packaging, 97, "正在打包學習包…")
        run_package(Path(state["work_dir"]))
        return state

    def route_after_coverage(state: HandoverState) -> str:
        return state.get("coverage_route") or "handover_gaps"

    def route_after_validate(state: HandoverState) -> str:
        return state.get("validate_route") or "fail"

    graph.add_node("ingest", ingest)
    graph.add_node("index", index)
    graph.add_node("extract", extract)
    graph.add_node("check_coverage", check_coverage)
    graph.add_node("extract_gap", extract_gap)
    graph.add_node("handover_gaps", handover_gaps)
    graph.add_node("outline", outline)
    graph.add_node("day_writer", day_writer)
    graph.add_node("quiz_smith", quiz_smith)
    graph.add_node("validate", validate)
    graph.add_node("repair", repair)
    graph.add_node("fail_validate", fail_validate)
    graph.add_node("render_diagrams", render)
    graph.add_node("export_pdf", export_pdf)
    graph.add_node("package", package)

    graph.add_edge(START, "ingest")
    graph.add_edge("ingest", "index")
    graph.add_edge("index", "extract")
    graph.add_edge("extract", "check_coverage")
    graph.add_conditional_edges(
        "check_coverage",
        route_after_coverage,
        {
            "extract_gap": "extract_gap",
            "handover_gaps": "handover_gaps",
        },
    )
    graph.add_edge("extract_gap", "check_coverage")
    graph.add_edge("handover_gaps", "outline")
    graph.add_edge("outline", "day_writer")
    graph.add_edge("day_writer", "quiz_smith")
    graph.add_edge("quiz_smith", "validate")
    graph.add_conditional_edges(
        "validate",
        route_after_validate,
        {
            "repair": "repair",
            "render_diagrams": "render_diagrams",
            "fail": "fail_validate",
        },
    )
    graph.add_edge("repair", "validate")
    graph.add_edge("render_diagrams", "export_pdf")
    graph.add_edge("export_pdf", "package")
    graph.add_edge("package", END)

    return graph.compile()
