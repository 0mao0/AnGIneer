"""文档解析阶段化管线：阶段注册表 + 依赖排序 + 状态派生 + 运行器 + 任务编排器。

设计约定：
- 每个阶段是 {key, title, kind(hard/soft), depends_on, run(ctx)} 的注册项；
- hard 阶段失败 → 终止后续阶段；soft 阶段失败 → 仅标记自身 failed，继续后续；
- 阶段状态通过 meta_store.upsert_parse_stage 持久化（doc_parse_stages 表）。
- ParseOrchestrator：创建/取消/重试解析任务，在后台线程驱动本管线并同步状态。
"""
import hashlib
import logging
import itertools
import os
import shutil
import subprocess
import threading
import time
import traceback
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Collection, Dict, List, Optional

from docs_core.docs_service import get_docs_service
from docs_core.step03_mineru_parse.mineru_parser import MinerUParser

logger = logging.getLogger(__name__)


# 延迟获取 AnGIneer LLM 客户端，避免循环导入
def _get_llm_client():
    try:
        from ai_inference.llm_client import llm_client
        return llm_client
    except ImportError:
        return None


STAGE_KIND_HARD = "hard"
STAGE_KIND_SOFT = "soft"


def _now_iso() -> str:
    """带本地时区偏移的当前时间 ISO（如 +08:00 / +00:00），前端可精确解析。"""
    return datetime.now().astimezone().isoformat()


class ParseTaskCancelledError(RuntimeError):
    """任务被用户取消（阶段内部取消点抛出，向上传播至任务线程）。"""


@dataclass
class StageContext:
    """跨阶段共享的上下文。"""
    task_id: str
    library_id: str
    doc_id: str
    file_path: str
    parse_options: Dict[str, Any] = field(default_factory=dict)
    source_path: Optional[str] = None
    ext: str = ".pdf"
    temp_output_dir: Optional[str] = None
    popo_ran: bool = False
    task_parser: Any = None
    input_summary: str = ""
    output_summary: str = ""
    meta_store: Any = None
    stage_started_at: Optional[str] = None
    stage_work_started_at: Optional[str] = None
    cancel_check: Optional[Callable[[], None]] = None
    fallback_target: Optional[str] = None
    stage_key: Optional[str] = None
    steps: List[Dict[str, Any]] = field(default_factory=list)
    sync_record: Optional[Callable[[str, str, str], None]] = None
    arrival_seq: int = 1
    page_count: int = 0
    is_scanned: bool = False

    def log_step(self, step: str, status: str = "done", detail: str = "") -> None:
        """记录阶段内分析步骤（如产物落盘 / 对齐检查 / 信号注入），立即持久化供前端展示。"""
        self.steps.append({"step": step, "status": status, "detail": detail})
        if self.meta_store is None:
            return
        try:
            self.meta_store.insert_parse_stage_step(
                self.doc_id, self.stage_key or "", step, status, detail
            )
        except Exception:
            logger.warning("记录分析步骤失败 doc=%s step=%s", self.doc_id, step, exc_info=True)
        # 同步最新步骤标题到任务 stage_message（只推标题，不含 detail/路径），
        # 供 PDF_Viewer 解析过程栏轮询展示
        try:
            get_docs_service().update_parse_task(self.task_id, stage_message=step)
        except Exception:
            logger.warning("同步解析步骤标题失败 task=%s step=%s", self.task_id, step, exc_info=True)


@dataclass
class StageDef:
    key: str
    title: str
    kind: str
    depends_on: List[str]
    run: Callable[["StageContext"], str]
    verify: Optional[Callable[["StageContext"], str]] = None
    step: str = ""


# ---- 阶段输入核查（启动前先核查输入，通过后通知前端「核查通过」再运行） ----

def _verify_source_file(ctx: StageContext) -> str:
    from docs_core.paths import resolve_node_file_path

    resolved = resolve_node_file_path(ctx.file_path)
    if resolved is None or not resolved.is_file():
        raise RuntimeError(f"源文件不存在: {ctx.file_path}")
    ctx.input_summary = ctx.file_path
    return "核查通过"


def _verify_convert_input(ctx: StageContext) -> str:
    from docs_core.step01_source_prep.source_prep import prepare_source

    if not ctx.source_path:
        ctx.source_path = prepare_source(ctx.library_id, ctx.doc_id, ctx.file_path)
    if not Path(ctx.source_path).is_file():
        raise RuntimeError(f"源文件不存在: {ctx.source_path}")
    ctx.input_summary = ctx.source_path
    return "核查通过"


def _verify_raw_parse_input(ctx: StageContext) -> str:
    """MinerU 输入必须是 PDF（convert 转换后或上传即 PDF）。"""
    from docs_core.docs_file_io import file_storage

    ctx.source_path = file_storage.resolve_pdf_input(ctx.library_id, ctx.doc_id)
    if not Path(ctx.source_path).is_file():
        raise RuntimeError(f"PDF 输入文件不存在: {ctx.source_path}")
    ctx.input_summary = ctx.source_path
    return "核查通过"


def _verify_mineru_raw_input(ctx: StageContext) -> str:
    import docs_core.paths as paths

    mineru_raw_dir = paths.get_mineru_raw_dir(ctx.library_id, ctx.doc_id)
    if not mineru_raw_dir.exists():
        raise RuntimeError(f"输入目录不存在: {mineru_raw_dir}")
    ctx.input_summary = str(mineru_raw_dir)
    return "核查通过"


def _verify_doc_blocks_graph_input(ctx: StageContext) -> str:
    import docs_core.paths as paths

    # 结构产物：jsonl + meta（Solo/PoPo 均产出）
    graph_path = paths.get_graph_jsonl_path(ctx.library_id, ctx.doc_id)
    if not graph_path.exists():
        raise RuntimeError(f"输入文件不存在: {graph_path}")
    ctx.input_summary = str(graph_path)
    return "核查通过"


# ---- 阶段执行函数 ----

def _mark_stage_queued(
    ctx: StageContext, step: str, detail_message: str, stage_message: str
) -> None:
    """排队等待资源：阶段/任务/解析记录状态同步为排队中，避免误显示解析耗时。"""
    ctx.log_step(step, "running", detail_message)
    if ctx.meta_store is not None and ctx.stage_key:
        ctx.meta_store.upsert_parse_stage(
            ctx.doc_id, ctx.stage_key, status="queued",
            message=stage_message,
            started_at=ctx.stage_started_at or _now_iso(),
        )
    try:
        get_docs_service().update_parse_task(
            ctx.task_id, stage="queued", stage_message=stage_message
        )
        if ctx.sync_record is not None:
            ctx.sync_record(ctx.task_id, ctx.doc_id, "queued")
    except Exception as exc:
        logger.warning("排队状态同步失败 task=%s: %s", ctx.task_id, exc)


def _mark_stage_running(ctx: StageContext, stage: str, message: str) -> None:
    """拿到资源槽位：阶段计时从此刻重新开始，排队等待不计入解析耗时。"""
    work_started = _now_iso()
    ctx.stage_work_started_at = work_started
    if ctx.meta_store is not None and ctx.stage_key:
        ctx.meta_store.upsert_parse_stage(
            ctx.doc_id, ctx.stage_key, status="running",
            message="核查通过",
            started_at=work_started,
        )
    try:
        get_docs_service().update_parse_task(
            ctx.task_id, stage=stage, stage_message=message
        )
        if ctx.sync_record is not None:
            ctx.sync_record(ctx.task_id, ctx.doc_id, "processing")
    except Exception as exc:
        logger.warning("解析状态同步失败 task=%s: %s", ctx.task_id, exc)


def _run_source_prep(ctx: StageContext) -> str:
    from docs_core.step01_source_prep.source_prep import prepare_source

    source_path = prepare_source(ctx.library_id, ctx.doc_id, ctx.file_path)
    ctx.input_summary = ctx.file_path
    ctx.output_summary = source_path
    ctx.source_path = source_path
    ctx.ext = Path(source_path).suffix.lower()
    return f"源文件就绪: {Path(source_path).name}"


def _run_convert(ctx: StageContext) -> str:
    # 输入核查已由 _verify_convert_input 完成（prepare_source 兜底解析源文件路径 + 存在性检查）
    ext = Path(ctx.source_path).suffix.lower()
    if ext == ".pdf":
        return "__skipped__:PDF 输入，无需转换"

    from docs_core.step02_convert2pdf.convert2pdf import convert_to_pdf

    if _CONVERT_GATE.should_wait(ctx.arrival_seq):
        _mark_stage_queued(
            ctx, "Office 转 PDF 排队",
            "等待 LibreOffice 转换槽位（前序文档转完后自动开始）",
            "等待 LibreOffice 转换槽位",
        )
    with convert_slot(ctx.cancel_check, arrival_seq=ctx.arrival_seq):
        _mark_stage_running(ctx, "convert", "Office 转 PDF 中")
        # 转换输出直接落在源文件目录（与上传的 docx 同目录），地址稳定且与上传位置一致
        source_dir = Path(ctx.source_path).parent
        source_dir.mkdir(parents=True, exist_ok=True)
        # 转换期间可取消：cancel_check 由任务线程注入，取消时终止 soffice 子进程
        pdf_path = convert_to_pdf(ctx.source_path, str(source_dir), cancel_check=ctx.cancel_check)
    ctx.input_summary = ctx.source_path
    ctx.output_summary = pdf_path
    ctx.source_path = pdf_path
    return "LibreOffice转换"


def _run_raw_parse(ctx: StageContext) -> str:
    # 输入核查已由 _verify_raw_parse_input 完成（resolve_pdf_input 取 source 目录最新 PDF）
    task_parser = ctx.task_parser
    if task_parser is None:
        raise RuntimeError("解析器不可用（任务已取消）")

    def _on_step(step: str, status: str = "done", detail: str = "") -> None:
        ctx.log_step(step, status, detail)

    ep_name = assign_mineru_endpoint(ctx.doc_id, (ctx.parse_options or {}).get("mineru_endpoint"))
    if ep_name:
        task_parser.preferred_endpoint = ep_name

    # 端点槽位**跟着实际使用的端点走**（2026-10-14）：偏好端点失败回退时会先释放它、
    # 再取回退端点的额度。若按"分配到的端点"取槽位，company 一断，这批文档就会占着
    # company 槽位去打 DGX——DGX 瞬间超并发（实测高并发会挂），故必须逐端点取得。
    def _slot_acquire(name: str) -> None:
        gate = _endpoint_gate(name)
        if gate.should_wait(ctx.arrival_seq):
            _mark_stage_queued(
                ctx, "MinerU 排队",
                f"等待 MinerU 资源（{name} 端点，前序任务完成后自动开始）",
                "等待 MinerU 资源",
            )
        gate.acquire(ctx.arrival_seq, ctx.cancel_check)
        # 拿到槽位才算"在跑"（与 convert 闸门一致）：阶段行的 started_at 即真实工作起点，
        # 排队时间不会被算进阶段耗时（2026-10-14 实踩：先标 running 再排队，甘特/折线里
        # raw_parse 被算成 120 并发、单篇 18 分钟）。
        _mark_stage_running(ctx, "raw_parse", "MinerU 解析中")

    def _slot_release(name: str) -> None:
        _endpoint_gate(name).release()

    task_parser.slot_acquire = _slot_acquire
    task_parser.slot_release = _slot_release
    try:
        # 解析器自建临时目录并负责落盘（save_markdown + save_parse_artifacts）
        parse_result = task_parser.parse_to_raw_artifacts(
            input_path=ctx.source_path,
            library_id=ctx.library_id,
            doc_id=ctx.doc_id,
            on_step=_on_step,
        )
    except Exception as exc:
        # MinerU 解析被取消（_abort_event 已设置）：转成取消异常，向上传播为 cancelled
        if getattr(task_parser, "_abort_event", None) is not None and task_parser._abort_event.is_set():
            raise ParseTaskCancelledError("用户手动取消任务") from exc
        ctx.log_step("MinerU 引擎解析", "failed", f"{type(exc).__name__}: {str(exc)[:200]}")
        raise
    if not parse_result.get("success"):
        ctx.log_step("MinerU 引擎解析", "failed", str(parse_result.get("error") or "MinerU解析失败")[:200])
        raise RuntimeError(parse_result.get("error") or "MinerU解析失败")

    persisted = parse_result.get("persisted") or {}
    ctx.input_summary = ctx.source_path
    ctx.output_summary = persisted.get("output_summary") or ""
    ctx.page_count = int(persisted.get("page_count") or 0)
    ctx.is_scanned = bool(persisted.get("ocr_retried"))
    has_images = bool(persisted.get("has_images"))
    backend = getattr(ctx.task_parser, "backend", None) or os.environ.get("MINERU_BACKEND", "hybrid-engine")
    return f"MinerU解析完成||{backend}||{'' if has_images else '（无图片资源）'}"


def _run_popo(ctx: StageContext) -> str:
    import docs_core.paths as paths
    from docs_core.step03_mineru_parse.popo_enhance import get_popo_pipeline
    from docs_core.docs_file_io import file_storage

    mineru_raw_dir = paths.get_mineru_raw_dir(ctx.library_id, ctx.doc_id)
    if not mineru_raw_dir.exists():
        ctx.log_step("PoPo 输入准备", "failed", str(mineru_raw_dir))
        raise FileNotFoundError(f"mineru_raw_dir not found at {mineru_raw_dir}")

    popo_output_dir = str(paths.get_popo_dir(ctx.library_id, ctx.doc_id))
    source_dir = paths.get_source_dir(ctx.library_id, ctx.doc_id)
    pipeline = get_popo_pipeline()
    if not getattr(pipeline, "is_available", lambda: True)():
        ctx.log_step("PoPo 强化", "skipped", "PoPo 子模块未安装，回退 Solo 构建")
        return "__skipped__: PoPo 子模块未安装，回退 Solo 构建"

    def _on_step(step: str, status: str = "done", detail: str = "") -> None:
        # 子阶段步骤回调同时作为取消点：PoPo 各子进程之间可响应取消
        if ctx.cancel_check is not None:
            ctx.cancel_check()
        ctx.log_step(step, status, detail)

    # PDF 源在 source 目录（转换后的 PDF 或上传的 PDF），重试/resume 时 ctx.source_path 可能为空，兜底解析
    source_pdf = str(ctx.source_path or "")
    if not source_pdf:
        pdfs = sorted(source_dir.glob("*.pdf"))
        if pdfs:
            source_pdf = str(pdfs[-1])
    if _POPO_GATE.should_wait(ctx.arrival_seq):
        _mark_stage_queued(
            ctx, "PoPo 4B 推理排队",
            "等待 PoPo 4B 推理资源（前序任务完成后自动开始）",
            "等待 PoPo 4B 推理资源",
        )
    attempt = 0
    while True:
        try:
            with popo_inference_slot(ctx.cancel_check, arrival_seq=ctx.arrival_seq):
                _mark_stage_running(ctx, "popo", "PoPo 4B 推理中")
                pipeline.run_full_pipeline(
                    mineru_raw_dir=str(mineru_raw_dir),
                    output_dir=popo_output_dir,
                    doc_id=ctx.doc_id,
                    source_pdf_path=source_pdf,
                    source_dir=str(source_dir),
                    on_step=_on_step,
                    cancel_check=ctx.cancel_check,
                )
            break
        except Exception as exc:
            if attempt < _POPO_INFERENCE_RETRIES and _is_transient_popo_failure(exc):
                attempt += 1
                backoff = _POPO_RETRY_BACKOFF_SECONDS * attempt
                logger.warning(
                    "PoPo 4B 推理瞬时失败（第 %d/%d 次），%.1fs 后重试 doc=%s: %s",
                    attempt, _POPO_INFERENCE_RETRIES, backoff, ctx.doc_id,
                    f"{type(exc).__name__}: {str(exc)[:160]}",
                )
                time.sleep(backoff)
                continue
            # popo 为可选信号源：失败回滚半成品并记录 fallback=solo，
            # structure 始终由 Solo 构建，有无 popo 信号都不受影响。
            _rollback_popo_products(ctx)
            ctx.fallback_target = "solo"
            if isinstance(exc, subprocess.CalledProcessError):
                stderr = (exc.stderr or "").strip()
                stdout = (exc.stdout or "").strip()
                detail = stderr or stdout or str(exc)
                raise RuntimeError(f"PoPo 子进程失败:\n{detail}") from exc
            raise

    enriched_blocks = file_storage.read_popo_enriched_blocks(ctx.library_id, ctx.doc_id)
    # output_summary 与 MinerU 一致：列出实际存在的产物文件（+ 连接），前端按固定清单打勾/打叉
    popo_dir = Path(popo_output_dir)
    output_parts = []
    for name in ("enriched_blocks.json", "document_tree.json"):
        path = popo_dir / name
        if path.exists():
            output_parts.append(str(path))
    ctx.input_summary = str(mineru_raw_dir)
    ctx.output_summary = " + ".join(output_parts) if output_parts else popo_output_dir
    return f"PoPo 强化完成，{len(enriched_blocks)} blocks（结构由 structure 阶段统一构建）"


def _rollback_popo_products(ctx: StageContext) -> None:
    """popo 失败时回滚已写产物，避免 structure 读到 popo 风格残缺数据。"""
    import docs_core.paths as paths
    from docs_core.docs_service import get_docs_service

    popo_dir = paths.get_popo_dir(ctx.library_id, ctx.doc_id)
    if popo_dir.exists():
        shutil.rmtree(popo_dir, ignore_errors=True)
    try:
        get_docs_service().index_store.clear_doc_blocks(ctx.doc_id)
    except Exception:
        logger.warning("popo rollback: clear doc_blocks failed", exc_info=True)
    mineru_md = paths.get_mineru_raw_dir(ctx.library_id, ctx.doc_id) / "content.md"
    parsed_md = paths.get_parsed_dir(ctx.library_id, ctx.doc_id) / "content.md"
    if mineru_md.exists():
        try:
            parsed_md.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(mineru_md), str(parsed_md))
        except OSError:
            logger.warning("popo rollback: restore markdown failed", exc_info=True)


def _run_structure(ctx: StageContext) -> str:
    """统一结构化者（单管线）：永远走 Solo 构建，PoPo 只作信号注入源。"""
    use_llm = bool(ctx.parse_options.get("use_llm", True))
    llm_model = str(ctx.parse_options.get("llm_model") or "").strip() or None
    return _run_structure_solo(ctx, use_llm=use_llm, llm_model=llm_model)


def _run_structure_solo(
    ctx: StageContext,
    *,
    use_llm: bool,
    llm_model: Optional[str],
) -> str:
    import docs_core.paths as paths
    from docs_core.step04_structure.solo2json_pipeline import build_structured_index_for_doc

    def _on_step(step: str, status: str = "done", detail: str = "") -> None:
        # 结构化子步骤回调同时作为取消点：规则构建/enrich/落盘之间可响应取消
        if ctx.cancel_check is not None:
            ctx.cancel_check()
        ctx.log_step(step, status, detail)

    result = build_structured_index_for_doc(
        library_id=ctx.library_id,
        doc_id=ctx.doc_id,
        strategy="doc_blocks_graph_v1",
        options={
            "use_llm": use_llm,
            "llm_model": llm_model,
        },
        on_step=_on_step,
    )
    stats = result.get("stats", {})
    # output_summary 与 PoPo/MinerU 一致：列出实际存在的产物文件（+ 连接），前端按固定清单打勾/打叉
    parsed_dir = paths.get_parsed_dir(ctx.library_id, ctx.doc_id)
    output_names = (
        "content.md",
        "doc_blocks_graph.jsonl",
        "doc_blocks_graph_meta.json",
    )
    output_parts = [str(parsed_dir / n) for n in output_names if (parsed_dir / n).exists()]
    ctx.input_summary = str(paths.get_mineru_raw_dir(ctx.library_id, ctx.doc_id))
    ctx.output_summary = " + ".join(output_parts) if output_parts else str(parsed_dir)
    # 按实际信号注入结果生成文案：Solo 永远是构建者，PoPo 只是信号源，不存在“降级”说法
    signal = (stats.get("popo_signal") or {}).get("injection") or {}
    applied = int(signal.get("applied") or 0)
    nodes_count = stats.get("nodes_count", 0)
    if applied > 0:
        return f"结构化完成（Solo 构建 + PoPo 信号 {applied} 处），{nodes_count} blocks"
    reason = str(signal.get("skipped_reason") or "")
    reason_text = {
        "no_popo": "PoPo 未产出",
        "no_middle": "缺少 middle.json",
        "alignment_degraded": "PoPo 对齐校验未过",
    }.get(reason, "PoPo 信号处理异常" if reason.startswith("error:") else "")
    suffix = f"，未注入 PoPo 信号（{reason_text}）" if reason_text else ""
    return f"结构化完成（Solo 构建{suffix}），{nodes_count} blocks"


def _run_figure_describe(ctx: StageContext) -> str:
    """图表 VLM 描述（soft）：为 doc_blocks_graph.jsonl 的图表块生成 figure_description。

    描述由 step05 fts（canonical_builder 拼接 caption+描述进 chunk）与
    step06/07 自动携带入索引/向量/图谱，本阶段只负责写回 jsonl。
    """
    import docs_core.paths as paths
    from docs_core.step04_structure.figure_describer import (
        describe_figures_in_graph,
        is_enabled,
    )

    if not is_enabled():
        ctx.log_step("图描述", "skipped", "FIGURE_DESCRIBE_ENABLED=0，跳过图描述")
        return "__skipped__: 图描述未启用（FIGURE_DESCRIBE_ENABLED=0）"

    graph_path = paths.get_graph_jsonl_path(ctx.library_id, ctx.doc_id)
    if _FIGURE_DESCRIBE_GATE.should_wait(ctx.arrival_seq):
        _mark_stage_queued(
            ctx, "图描述排队",
            "等待图描述 VLM 资源（前序任务完成后自动开始）",
            "等待图描述 VLM 资源",
        )

    def _on_node(block_uid: str, status: str, detail: str) -> None:
        if ctx.cancel_check is not None:
            ctx.cancel_check()
        ctx.log_step(f"图描述 {block_uid or '汇总'}", status, detail)

    with figure_describe_slot(ctx.cancel_check, arrival_seq=ctx.arrival_seq):
        _mark_stage_running(ctx, "figure_describe", "图描述 VLM 推理中")
        stats = describe_figures_in_graph(
            ctx.library_id,
            ctx.doc_id,
            on_node=_on_node,
            cancel_check=ctx.cancel_check,
            max_workers=1,   # 每篇同时只发一个请求；在飞请求数由上面那个闸门单点控制
        )

    ctx.input_summary = str(graph_path)
    ctx.output_summary = (
        f"figure_description 写回 doc_blocks_graph.jsonl："
        f"新生成 {stats['described']}，已有 {stats['already']}，"
        f"缺图 {stats['missing_images']}，失败 {stats['errors']}"
    )
    return f"图描述完成（新生成 {stats['described']} 张，已有 {stats['already']} 张）"


def _run_fts(ctx: StageContext) -> str:
    import docs_core.paths as paths
    from docs_core.step05_sqlite_fts.sqlite_index import build_sqlite_index_from_graph

    def _on_step(step: str, status: str = "done", detail: str = "") -> None:
        # 子步骤回调兼作取消点
        if ctx.cancel_check is not None:
            ctx.cancel_check()
        ctx.log_step(step, status, detail)

    if _FTS_GATE.should_wait(ctx.arrival_seq):
        _mark_stage_queued(
            ctx, "FTS 建索引排队",
            "等待 SQLite/FTS 建索引槽位（同一时刻只允许少量并发写库）",
            "等待 FTS 建索引槽位",
        )
    with fts_slot(ctx.cancel_check, arrival_seq=ctx.arrival_seq):
        _mark_stage_running(ctx, "fts", "SQLite+FTS 建索引中")
        result = build_sqlite_index_from_graph(ctx.library_id, ctx.doc_id, on_step=_on_step)
    ctx.input_summary = str(paths.get_graph_jsonl_path(ctx.library_id, ctx.doc_id))
    ctx.output_summary = (
        f"canonical SQLite + doc_blocks + segments + canonical_chunk_fts "
        f"({result.get('canonical_blocks_count', 0)} blocks)"
    )
    return f"SQLite 建库完成，FTS 重建完成（{result.get('canonical_blocks_count', 0)} blocks）"


# ---- MinerU/GPU 并发闸门：同一时刻最多 MINERU_MAX_CONCURRENCY 个任务占用 GPU ----
class _FifoGpuGate:
    """进程级 GPU 闸门：按「到达本闸门」的先后排队（本闸门独立 FCFS）。

    2026-10-14 语义修订（消除跨阶段头阻塞）：
    - 旧语义：按任务提交序号严格先来先服务——序号靠前的任务即使还在更早的阶段
      （例：PoPo 闸门面对还在 MinerU 里的前序任务），也会占住本闸门队首；即使有空槽，
      后序任务也不能进入（实测 PoPo 空槽硬等 88–100 分钟、MinerU 最长等 574 分钟）。
    - 新语义：只对「已经到达本闸门」的任务排队——到达即领本闸门排队号，先到本阶段者
      先获得槽位；仍在更早阶段的任务不占本闸门排位（尚未到达 = 与本闸门无关）。
      三个闸门各自独立排队、跨阶段互不绑序；阶段内仍是 FCFS（可解释、无饿死）。

    arrival_seq 在本类中只作任务身份键：同一任务重复请求（PoPo 瞬时失败重试）
    沿用同一排队号；排队号已消耗的重复请求按「有空槽即直通」处理。
    """

    def __init__(self, max_concurrency: int = 1) -> None:
        self._max_concurrency = max(1, int(max_concurrency))
        self._cond = threading.Condition()
        self._tokens = self._max_concurrency
        self._next_ticket = 1                       # 下一个待发放的排队号
        self._serving = 1                           # 当前应被服务的排队号（队首）
        self._tickets: dict[int, int] = {}          # 任务键 -> 排队号
        self._cancelled_tickets: set[int] = set()   # 未获槽即取消/退出的排队号

    @property
    def available(self) -> int:
        """当前空闲令牌数（仅用于排队提示）。"""
        with self._cond:
            return self._tokens

    def _skip_cancelled_locked(self) -> None:
        """跳过未获槽即取消/退出的排队号，避免后续任务永久等待。"""
        while self._serving in self._cancelled_tickets:
            self._cancelled_tickets.discard(self._serving)
            self._serving += 1

    def should_wait(self, arrival_seq: int) -> bool:
        """该任务此刻到闸是否要排队（用于 queued 状态提示；不分配排队号）。

        预测口径与 acquire 一致：队首还有更早到达的任务、或无空闲槽 -> 会排队。
        """
        with self._cond:
            ticket = self._tickets.get(arrival_seq)
            if ticket is None:
                ticket = self._next_ticket  # 预测：新到者将拿到队尾排队号
            if ticket < self._serving:
                # 排队号已消耗的重复请求（如 PoPo 重试）：有空槽即直通
                return self._tokens <= 0
            return ticket != self._serving or self._tokens <= 0

    def skip(self, arrival_seq: int) -> None:
        """任务在获槽前退出时作废其排队号。

        未到过本闸门的任务（无排队号）为无操作——新语义下它们不占本闸门排位；
        已获槽的任务（排队号已消耗）同为无操作。闸门内等待被取消的路径由
        acquire 自行登记，本方法只作任务退出的兜底。
        """
        with self._cond:
            ticket = self._tickets.get(arrival_seq)
            if ticket is not None and ticket >= self._serving:
                self._cancelled_tickets.add(ticket)
                self._skip_cancelled_locked()
                self._cond.notify_all()

    def acquire(
        self,
        arrival_seq: int,
        cancel_check: Optional[Callable[[], None]] = None,
        poll_interval: float = 0.5,
    ) -> None:
        """按本闸门排队号阻塞等待令牌；等待期间按 poll_interval 轮询取消标志。"""
        with self._cond:
            ticket = self._tickets.get(arrival_seq)
            if ticket is None:
                ticket = self._next_ticket
                self._next_ticket += 1
                self._tickets[arrival_seq] = ticket
            while True:
                if ticket == self._serving and self._tokens > 0:
                    self._tokens -= 1
                    self._serving += 1
                    self._skip_cancelled_locked()
                    self._cond.notify_all()
                    return
                if ticket < self._serving and self._tokens > 0:
                    # 重复请求兜底（如 PoPo 瞬时失败重试）：排队号已消耗，有空槽直通
                    logger.warning(
                        "GPU 闸门直通（重复请求）: key=%s ticket=%s serving=%s tokens=%s pid=%s",
                        arrival_seq, ticket, self._serving, self._tokens, os.getpid(),
                    )
                    self._tokens -= 1
                    return
                if cancel_check is not None:
                    try:
                        cancel_check()  # 取消时抛 ParseTaskCancelledError，不消费令牌
                    except BaseException:
                        # 排队期间被取消：作废排队号并让位给后续任务
                        if ticket >= self._serving:
                            self._cancelled_tickets.add(ticket)
                            self._skip_cancelled_locked()
                        self._cond.notify_all()
                        raise
                self._cond.wait(poll_interval)

    def release(self) -> None:
        with self._cond:
            self._tokens += 1
            self._cond.notify_all()


_MINERU_MAX_CONCURRENCY = 1
try:
    _MINERU_MAX_CONCURRENCY = max(
        1, int(os.getenv("MINERU_MAX_CONCURRENCY", "1").strip() or "1")
    )
except (TypeError, ValueError):
    _MINERU_MAX_CONCURRENCY = 1

_MINERU_GPU_GATE = _FifoGpuGate(_MINERU_MAX_CONCURRENCY)


@contextmanager
def mineru_gpu_slot(
    cancel_check: Optional[Callable[[], None]] = None,
    arrival_seq: int = 1,
):
    """MinerU 任务占用的 GPU 槽位：按到达本闸门的先后排队（本闸门独立 FCFS），进入 raw_parse 前获取。"""
    _MINERU_GPU_GATE.acquire(arrival_seq, cancel_check)
    try:
        yield
    finally:
        _MINERU_GPU_GATE.release()


# ---- MinerU 端点分流（2026-10-14：company 端点分担大批量解析） ----
# 动机：单端点并发上限 = 全队列吞吐上限（MINERU_MAX_CONCURRENCY=2 → 约 3 篇/分钟）。
# 做法：按 doc_id 哈希把文档分到 MINERU_ENDPOINT_WEIGHTS 里的端点（确定性、无需改 API），
# 每个端点在 MinerU 端各自一个到达序闸门，cap 由 MINERU_ENDPOINT_CAPS 指定
# （未指定的端点回落 MINERU_MAX_CONCURRENCY）。端点偏好写入解析器，其余端点仍作回退。
def _parse_kv_int(raw: str) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for part in (raw or "").split(","):
        if ":" not in part:
            continue
        k, _, v = part.partition(":")
        try:
            out[k.strip()] = max(1, int(v))
        except (TypeError, ValueError):
            continue
    return out


_MINERU_ENDPOINT_WEIGHTS = _parse_kv_int(os.getenv("MINERU_ENDPOINT_WEIGHTS", ""))
_MINERU_ENDPOINT_CAPS = _parse_kv_int(os.getenv("MINERU_ENDPOINT_CAPS", ""))
_ENDPOINT_GATES: Dict[str, _FifoGpuGate] = {}


def _endpoint_gate(name: Optional[str]) -> _FifoGpuGate:
    """端点闸门：按端点名各持一个（端点内 FCFS）；无端点名时用全局闸门。"""
    if not name:
        return _MINERU_GPU_GATE
    gate = _ENDPOINT_GATES.get(name)
    if gate is None:
        gate = _FifoGpuGate(_MINERU_ENDPOINT_CAPS.get(name, _MINERU_MAX_CONCURRENCY))
        _ENDPOINT_GATES[name] = gate
        logger.info("MinerU 端点闸门: %s cap=%s", name, _MINERU_ENDPOINT_CAPS.get(name, _MINERU_MAX_CONCURRENCY))
    return gate


def assign_mineru_endpoint(doc_id: str, explicit: Optional[str] = None) -> Optional[str]:
    """把文档分到某个 MinerU 端点（None = 不指定，走 MINERU_CONFIGS 顺序）。"""
    if explicit:
        return explicit
    total = sum(_MINERU_ENDPOINT_WEIGHTS.values())
    if not _MINERU_ENDPOINT_WEIGHTS or total <= 0:
        return None
    slot = int(hashlib.sha256(str(doc_id).encode()).hexdigest()[:8], 16) % total
    acc = 0
    for name, weight in _MINERU_ENDPOINT_WEIGHTS.items():
        acc += weight
        if slot < acc:
            return name
    return None


@contextmanager
def mineru_endpoint_slot(name: Optional[str], cancel_check: Optional[Callable[[], None]] = None,
                         arrival_seq: int = 1):
    """按端点取槽位（端点内按到达序 FCFS）。"""
    gate = _endpoint_gate(name)
    gate.acquire(arrival_seq, cancel_check)
    try:
        yield
    finally:
        gate.release()


def _env_int(name: str, default: int) -> int:
    """读取环境变量整数，非法/缺省回退默认值。"""
    try:
        raw = os.getenv(name, "").strip()
        return int(raw) if raw else default
    except (TypeError, ValueError):
        return default


_POPO_MAX_CONCURRENCY = max(1, _env_int("POPO_MAX_CONCURRENCY", 1))
_POPO_GATE = _FifoGpuGate(_POPO_MAX_CONCURRENCY)
_POPO_INFERENCE_RETRIES = max(0, _env_int("POPO_INFERENCE_RETRIES", 1))
_POPO_RETRY_BACKOFF_SECONDS = 5.0


@contextmanager
def popo_inference_slot(
    cancel_check: Optional[Callable[[], None]] = None,
    arrival_seq: int = 1,
):
    """PoPo 4B 推理（远端 vLLM）槽位：按到达本闸门的先后排队（本闸门独立 FCFS），防止并发打满远端。"""
    _POPO_GATE.acquire(arrival_seq, cancel_check)
    try:
        yield
    finally:
        _POPO_GATE.release()


_FIGURE_DESCRIBE_MAX_CONCURRENCY = max(1, _env_int("FIGURE_DESCRIBE_MAX_CONCURRENCY", 1))
_FIGURE_DESCRIBE_GATE = _FifoGpuGate(_FIGURE_DESCRIBE_MAX_CONCURRENCY)
# 本闸门锁的是"一篇文档的图描述"，阶段路径再固定 max_workers=1（每篇同时只发一个请求），
# 所以 FIGURE_DESCRIBE_MAX_CONCURRENCY 直接等于远端 LLM 的在飞请求数上限——只有这一个旋钮。


@contextmanager
def figure_describe_slot(
    cancel_check: Optional[Callable[[], None]] = None,
    arrival_seq: int = 1,
):
    """图描述 VLM（远端 chat 端点）槽位：按到达本闸门的先后排队（本闸门独立 FCFS）。"""
    _FIGURE_DESCRIBE_GATE.acquire(arrival_seq, cancel_check)
    try:
        yield
    finally:
        _FIGURE_DESCRIBE_GATE.release()


# ---- LibreOffice 转换闸门：压住本机 soffice 进程数（2026-10-14 大批量导入实踩） ----
# 事故：编排器按篇起线程（任务总数无上限），convert 阶段原先没有闸门 → 同时转几千篇 PDF；
# Windows 上 soffice 进程堆积到 1,647 个、单篇转换被拖到 180s 超时 → 全库判失败。
# 语义与其余三个闸门一致：按「到达本闸门」序 FCFS，同一任务重复请求沿用同一排队号。
_CONVERT_MAX_CONCURRENCY = max(1, _env_int("CONVERT_MAX_CONCURRENCY", 2))
_CONVERT_GATE = _FifoGpuGate(_CONVERT_MAX_CONCURRENCY)


# ---- SQLite/FTS 建索引闸门：压住并发写库（2026-10-14 大批量导入实踩） ----
# 事故：fts 阶段无闸门 → 百余任务同时写同一个组 sqlite（canonical+FTS）→
# 121 篇 OperationalError: database is locked、123 篇假死，全链完成数卡在 55 篇不动。
# 与 convert 闸门同构：按到达序 FCFS，默认 2。
_FTS_MAX_CONCURRENCY = max(1, _env_int("FTS_MAX_CONCURRENCY", 2))
_FTS_GATE = _FifoGpuGate(_FTS_MAX_CONCURRENCY)


# ---- 向量索引闸门：压住并发 embed 请求（2026-10-17 22:1x 大批量补跑实踩） ----
# 事故：vectors 阶段无闸门 → 补跑数百篇同时进本阶段 → 数百并发 embed 请求把网关上游
# 打出一片 502，客户端 5 次重试耗尽后降级 256 维哈希被写库维度校验拒绝（8 分钟 18 篇失败）。
# 嵌入请求为秒级短请求，默认 8 槽足够喂满端点，同时不再打崩上游。
_VECTORS_MAX_CONCURRENCY = max(1, _env_int("VECTORS_MAX_CONCURRENCY", 8))
_VECTORS_GATE = _FifoGpuGate(_VECTORS_MAX_CONCURRENCY)


@contextmanager
def vectors_slot(
    cancel_check: Optional[Callable[[], None]] = None,
    arrival_seq: int = 1,
):
    """向量索引槽位：按到达本闸门的先后排队（本闸门独立 FCFS）。"""
    _VECTORS_GATE.acquire(arrival_seq, cancel_check)
    try:
        yield
    finally:
        _VECTORS_GATE.release()


@contextmanager
def fts_slot(
    cancel_check: Optional[Callable[[], None]] = None,
    arrival_seq: int = 1,
):
    """SQLite/FTS 建索引槽位：按到达本闸门的先后排队（本闸门独立 FCFS）。"""
    _FTS_GATE.acquire(arrival_seq, cancel_check)
    try:
        yield
    finally:
        _FTS_GATE.release()


@contextmanager
def convert_slot(
    cancel_check: Optional[Callable[[], None]] = None,
    arrival_seq: int = 1,
):
    """LibreOffice 转换槽位：按到达本闸门的先后排队（本闸门独立 FCFS）。"""
    _CONVERT_GATE.acquire(arrival_seq, cancel_check)
    try:
        yield
    finally:
        _CONVERT_GATE.release()


_POPO_TRANSIENT_MARKERS = (
    "timeout", "timed out", "connection", "retries", "429",
    "overloaded", "unavailable", "500", "503",
)


def _is_transient_popo_failure(exc: Exception) -> bool:
    """PoPo 子进程失败是否为瞬时错误（远端抖动/超时），决定是否重试。"""
    from docs_core.step03_mineru_parse.popo_enhance import PopoEndpointUnavailableError

    # 端点全挂是 popo_enhance 在"子进程退出码为 0、静默返回空串"时主动抛的：
    # 必须走重试，否则一次抖动就把这一篇的 PoPo 判定白丢（2026-09-20 实测 25 篇里 1 篇）。
    if isinstance(exc, PopoEndpointUnavailableError):
        return True
    if isinstance(exc, subprocess.TimeoutExpired):
        return True
    if isinstance(exc, subprocess.CalledProcessError):
        text = f"{exc.stderr or ''} {exc.stdout or ''}".lower()
        return any(marker in text for marker in _POPO_TRANSIENT_MARKERS)
    return False


def _run_vectors(ctx: StageContext) -> str:
    from docs_core.docs_service import get_docs_service
    from docs_core.step06_vectors.embedding_provider import default_embedding_provider

    def _on_step(step: str, status: str = "done", detail: str = "") -> None:
        # 子步骤回调兼作取消点
        if ctx.cancel_check is not None:
            ctx.cancel_check()
        ctx.log_step(step, status, detail)

    if _VECTORS_GATE.should_wait(ctx.arrival_seq):
        _mark_stage_queued(
            ctx, "向量索引排队",
            "等待向量索引槽位（控制并发 embed 请求，避免压垮网关）",
            "等待向量索引槽位",
        )
    with vectors_slot(ctx.cancel_check, arrival_seq=ctx.arrival_seq):
        ks = get_docs_service()
        ks.rebuild_document_vectors(ctx.doc_id, on_step=_on_step)
    import docs_core.paths as paths
    ctx.input_summary = str(paths.get_graph_jsonl_path(ctx.library_id, ctx.doc_id))
    ctx.output_summary = "vector store (entity_id + embedding)"

    flags = getattr(default_embedding_provider, "runtime_flags", [])
    if "embedding_hash_fallback" in flags:
        return "向量索引完成（degraded: embedding_hash_fallback）"

    return "向量索引完成"


def _run_graph(ctx: StageContext) -> str:
    from docs_core.step07_graph.push_to_graph import push_to_graph
    from docs_core.step07_graph.auto_extract import auto_llm_enabled, spawn_llm_graph_extraction

    def _on_step(step: str, status: str = "done", detail: str = "") -> None:
        # 子步骤回调兼作取消点
        if ctx.cancel_check is not None:
            ctx.cancel_check()
        ctx.log_step(step, status, detail)

    result = push_to_graph(ctx.library_id, ctx.doc_id, on_step=_on_step)
    if not result.get("pushed"):
        error = result.get("error", "未知错误")
        raise RuntimeError(f"图谱构建失败: {error}")

    import docs_core.paths as paths
    ctx.input_summary = str(paths.get_graph_jsonl_path(ctx.library_id, ctx.doc_id))
    ctx.output_summary = "knowledge_graph.sqlite (entities + relations)"

    entities = result.get("entities_count", 0)
    relations = result.get("relations_count", 0)

    if auto_llm_enabled():
        spawn_llm_graph_extraction(ctx.library_id, ctx.doc_id)

    return f"图谱完成，{entities} 实体，{relations} 关系"


# step = 9 个阶段的位次编号（1..9，与前端抽屉/进度条同口径）；序号只在 step 里，title 不再带前缀。
STAGE_REGISTRY: Dict[str, StageDef] = {s.key: s for s in [
    StageDef("source_prep", "源文件准备", STAGE_KIND_HARD, [], _run_source_prep, _verify_source_file, step="1"),
    StageDef("convert", "格式转换", STAGE_KIND_HARD, ["source_prep"], _run_convert, _verify_convert_input, step="2"),
    StageDef("raw_parse", "MinerU解析", STAGE_KIND_HARD, ["convert"], _run_raw_parse, _verify_raw_parse_input, step="3"),
    StageDef("popo", "PoPo强化", STAGE_KIND_SOFT, ["raw_parse"], _run_popo, _verify_mineru_raw_input, step="4"),
    StageDef("structure", "结构化（Solo 唯一构建者）", STAGE_KIND_HARD, ["raw_parse"], _run_structure, _verify_mineru_raw_input, step="5"),
    StageDef("figure_describe", "图描述（VLM）", STAGE_KIND_SOFT, ["structure"], _run_figure_describe, _verify_doc_blocks_graph_input, step="6"),
    StageDef("fts", "SQLite+FTS", STAGE_KIND_HARD, ["structure"], _run_fts, _verify_doc_blocks_graph_input, step="7"),
    StageDef("vectors", "向量索引", STAGE_KIND_SOFT, ["fts"], _run_vectors, _verify_doc_blocks_graph_input, step="8"),
    StageDef("graph", "知识图谱", STAGE_KIND_SOFT, ["structure"], _run_graph, _verify_doc_blocks_graph_input, step="9"),
]}

_PIPELINE_ORDER = [
    "source_prep", "convert", "raw_parse", "popo", "structure", "figure_describe", "fts", "vectors", "graph",
]


def resolve_stage_order(stages) -> List[str]:
    if isinstance(stages, str):
        if stages != "all":
            raise ValueError(f"未知的 stages 参数: {stages}")
        return list(_PIPELINE_ORDER)
    unknown = [s for s in stages if s not in STAGE_REGISTRY]
    if unknown:
        raise ValueError(f"未知阶段: {unknown}")
    selected = set(stages)
    return [key for key in _PIPELINE_ORDER if key in selected]


_DEPENDENCY_SKIP_MARKERS = ("前置硬阶段", "依赖阶段失败")


def is_dependency_skip_message(message: Any) -> bool:
    """判断 skipped 是否为前置依赖失败导致的连带跳过（此类跳过不应视为已完成）。"""
    text = str(message or "")
    return any(marker in text for marker in _DEPENDENCY_SKIP_MARKERS)


def _format_elapsed_hms(seconds: float) -> str:
    """耗时文案：<60s 保留 1 位小数（如 5.3秒），≥60s 取整为 xx小时xx分xx秒（均为整数）。"""
    if seconds < 60:
        return f"{round(seconds, 1)}秒"
    total = int(round(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}小时{minutes}分{secs}秒"
    return f"{minutes}分{secs}秒"


def _missing_core_artifacts(library_id: str, doc_id: str) -> List[str]:
    """completed 状态应保证的核心结构产物；缺失时返回文件名列表。"""
    import docs_core.paths as paths

    parsed_dir = paths.get_parsed_dir(library_id, doc_id)
    missing = []
    for name in ("doc_blocks_graph.jsonl", "doc_blocks_graph_meta.json"):
        if not (parsed_dir / name).exists():
            missing.append(name)
    return missing


def derive_overall_status(
    stage_status: Dict[str, str],
    *,
    dependency_skipped: Optional[Collection[str]] = None,
) -> str:
    values = list(stage_status.values())
    if any(v == "running" for v in values):
        return "processing"
    if not values:
        return "queued"
    hard_failed = any(
        stage_status.get(key) == "failed"
        for key, stage in STAGE_REGISTRY.items()
        if stage.kind == STAGE_KIND_HARD
    )
    if hard_failed:
        return "failed"
    # 被兜底的失败不计入 partial：PoPo 失败但 Solo 成功 → 结构强化已完成
    effective = dict(stage_status)
    if effective.get("popo") == "failed" and effective.get("structure") == "completed":
        effective["popo"] = "completed"
    # figure_describe 阶段上线前已完成的存量文档没有该阶段记录：
    # 其余阶段全部终态时视为 skipped，避免旧文档整体被误判为 processing
    if "figure_describe" not in effective and all(
        effective.get(key) in ("completed", "skipped")
        for key in STAGE_REGISTRY
        if key != "figure_describe"
    ):
        effective["figure_describe"] = "skipped"
    values = list(effective.values())
    if any(v == "failed" for v in values):
        return "partial"
    if dependency_skipped:
        for key in dependency_skipped:
            if effective.get(key) == "skipped":
                return "partial"
    if all(effective.get(key) in ("completed", "skipped") for key in STAGE_REGISTRY):
        return "completed"
    return "processing"


def derive_merged_overall_status(
    existing_stage_status: Dict[str, str],
    launched_results: Dict[str, str],
    *,
    dependency_skipped: Optional[Collection[str]] = None,
) -> str:
    """单阶段重跑后的整体状态：已完成的阶段 + 本次运行结果合并推导。

    避免只按本次启动的阶段判定，导致软阶段（vectors/graph/popo）失败时
    把内容已完成的记录整体覆盖成 failed。
    """
    merged = dict(existing_stage_status or {})
    merged.update(launched_results or {})
    return derive_overall_status(merged, dependency_skipped=dependency_skipped)


def _resolve_resume_scope(requested_stages: str, present_keys: set) -> List[str]:
    """确定 resume 目标阶段范围。

    requested="all" → 整条流水线（管理后台「解析」用：中断文档补齐缺的阶段）；
    逗号清单 → 显式子集；空 → v1 旧语义：行内出现过的阶段 ∪ structure（无行 → ["structure"]）。
    """
    if requested_stages and requested_stages.strip():
        if requested_stages.strip().lower() == "all":
            return list(_PIPELINE_ORDER)
        keys = {s.strip() for s in requested_stages.split(",") if s.strip()}
        return [k for k in _PIPELINE_ORDER if k in keys]
    if not present_keys:
        return ["structure"]
    keys = set(present_keys)
    keys.add("structure")
    return [k for k in _PIPELINE_ORDER if k in keys]


def compute_resume_stages(requested_stages: str, stage_rows: List[Dict[str, Any]]) -> List[str]:
    """断点续跑要重新调度的阶段（纯函数；docs-api v1 /resume 与管理后台 retry 共用）。

    原为 docs-api/resume_stages.py 自带实现，其 _PIPELINE_ORDER 缺 figure_describe 与
    docs-core 已漂移（2026-09-15），统一到本模块、docs-api 侧只做再导出。
    判定：completed 视为完成；合法 skipped（非依赖失败连带）视为完成；
    running/failed/queued/pending/skipped(依赖连带)/缺行 → 需要调度。
    """
    rows_by_stage = {str(r.get("stage") or "").strip(): r for r in stage_rows if r.get("stage")}
    scope = _resolve_resume_scope(str(requested_stages or ""), set(rows_by_stage))
    remaining = []
    for key in scope:
        row = rows_by_stage.get(key)
        if row is None:
            remaining.append(key)
            continue
        status = str(row.get("status") or "")
        if status == "completed":
            continue
        if status == "skipped" and not is_dependency_skip_message(row.get("message")):
            continue
        remaining.append(key)
    return remaining


def reset_parse_stage_records(meta_store, doc_id: str) -> None:
    """全量重跑前清空阶段记录与子阶段步骤，避免解析阶段抽屉展示上一次解析的残留。"""
    clear_stages = getattr(meta_store, "clear_parse_stages", None)
    if callable(clear_stages):
        clear_stages(doc_id)
    clear_steps = getattr(meta_store, "clear_parse_stage_steps", None)
    if callable(clear_steps):
        clear_steps(doc_id)


def run_pipeline(
    ctx: StageContext,
    stages,
    *,
    meta_store,
    on_stage_update: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    raise_if_cancelled: Optional[Callable[[], None]] = None,
) -> Dict[str, str]:
    order = resolve_stage_order(stages)
    results: Dict[str, str] = {}
    for key in order:
        stage = STAGE_REGISTRY[key]
        failed_deps = [d for d in stage.depends_on if results.get(d) == "failed"]
        if failed_deps:
            results[key] = "skipped"
            meta_store.upsert_parse_stage(ctx.doc_id, key, status="skipped",
                                          message=f"依赖阶段失败: {failed_deps}")
            continue
        if raise_if_cancelled:
            raise_if_cancelled()
        # reset per-stage analysis steps on rerun
        clear_steps = getattr(meta_store, "clear_parse_stage_steps", None)
        if callable(clear_steps):
            clear_steps(ctx.doc_id, key)
        started = _now_iso()
        meta_store.upsert_parse_stage(ctx.doc_id, key, status="running", started_at=started)
        ctx.input_summary = ""
        ctx.output_summary = ""
        # 页数/扫描件元数据仅由产生它的阶段（MinerU raw_parse）落库，
        # 每阶段重置，避免从上一个阶段泄漏到后续阶段记录。
        ctx.page_count = 0
        ctx.is_scanned = False
        ctx.stage_key = key
        ctx.steps = []
        ctx.meta_store = meta_store
        ctx.stage_started_at = started
        ctx.stage_work_started_at = None
        ctx.cancel_check = raise_if_cancelled
        try:
            # 启动前先核查输入：通过则先通知前端「核查通过」，再驱动本阶段运行
            if stage.verify is not None:
                stage.verify(ctx)
                meta_store.upsert_parse_stage(
                    ctx.doc_id, key, status="running", message="核查通过",
                    input_summary=ctx.input_summary, started_at=started,
                )
            message = stage.run(ctx) or "完成"
            if str(message).startswith("__skipped__"):
                results[key] = "skipped"
                meta_store.upsert_parse_stage(
                    ctx.doc_id, key, status="skipped",
                    message=str(message)[len("__skipped__"):],
                    started_at=started,
                    finished_at=_now_iso(),
                )
                continue
            results[key] = "completed"
            work_started = ctx.stage_work_started_at or started
            elapsed = 0.0
            try:
                elapsed = max(
                    0.0, time.time() - datetime.fromisoformat(work_started).timestamp()
                )
            except ValueError:
                elapsed = 0.0
            meta_store.upsert_parse_stage(
                ctx.doc_id, key, status="completed",
                message=f"{message}，耗时{_format_elapsed_hms(elapsed)}",
                started_at=None, finished_at=_now_iso(),
                input_summary=ctx.input_summary, output_summary=ctx.output_summary,
                page_count=getattr(ctx, "page_count", 0) or 0,
                is_scanned=bool(getattr(ctx, "is_scanned", False)),
            )
        except ParseTaskCancelledError:
            # 用户取消：不做 failed 标记，直接向上传播至任务线程
            raise
        except Exception as exc:
            results[key] = "failed"
            error_message = f"{type(exc).__name__}: {exc}"
            fallback = str(getattr(ctx, "fallback_target", None) or "")
            meta_store.upsert_parse_stage(
                ctx.doc_id, key, status="failed",
                error=error_message + "\n" + traceback.format_exc(limit=3),
                started_at=None, finished_at=_now_iso(),
                fallback=fallback,
            )
            ctx.fallback_target = None
            if stage.kind == STAGE_KIND_HARD:
                for rest in order[order.index(key) + 1:]:
                    results[rest] = "skipped"
                    meta_store.upsert_parse_stage(ctx.doc_id, rest, status="skipped",
                                                  message=f"前置硬阶段 {key} 失败")
                break
        if on_stage_update:
            on_stage_update(key, dict(results))
    return results


def validate_stage_retry(node_status: str, stage_key: str) -> None:
    if stage_key not in STAGE_REGISTRY:
        raise ValueError(f"未知阶段: {stage_key}")
    if node_status == "processing":
        raise ValueError("文档正在解析中，请先取消当前任务")


# 全局 FIFO 序号：所有 ParseOrchestrator 实例共享同一个计数器，
# 避免管理后台和外部 API 各自从 1 开始编号，导致 MinerU GPU 闸门误判旧序号并取消任务。
_GLOBAL_ARRIVAL_COUNTER = itertools.count(1)

class ParseOrchestrator:
    """负责 API 层与解析主链之间的编排。"""

    def __init__(
        self,
        record_updater: Optional[Callable[[str, str, str, Optional[str]], None]] = None,
        record_actor: str = "system",
    ) -> None:
        """record_updater(task_id, doc_id, status, error)：把任务状态同步到解析记录表。

        不传时用 docs-core 自带实现（`docs_core.parse_records_store`）——脚本/进程内路径也必须
        留流水，否则文档只进 nodes 不进 parse_records，管理端整篇看不见（2026-09-14 实测 189/295）。
        `record_actor` 是新建记录时的 uploaded_by 兜底，用于区分来源（如 `system:omnidocbench-eval`）。
        """
        self._threads: Dict[str, threading.Thread] = {}
        self._parsers: Dict[str, MinerUParser] = {}
        self._cancelled: set = set()
        if record_updater is None:
            from docs_core.parse_records_store import sync_record_for_task

            actor = record_actor or "system"
            record_updater = lambda task_id, doc_id, status, error=None: sync_record_for_task(
                task_id, doc_id, status, error, actor=actor)
        self._record_updater = record_updater
        self._arrival_counter = _GLOBAL_ARRIVAL_COUNTER

    def _sync_record(self, task_id: str, doc_id: str, status: str, error: Optional[str] = None) -> None:
        """把任务状态同步到解析记录表（默认实现见 docs_core.parse_records_store）。"""
        if not self._record_updater:
            return
        try:
            self._record_updater(task_id, doc_id, status, error)
        except Exception as exc:
            logger.warning("同步解析记录失败 task=%s: %s", task_id, exc)

    def ensure_document(self, library_id: str, file_path: str, doc_id: Optional[str] = None) -> str:
        """注册或补全文档节点，确保解析主链使用统一文档标识。"""
        ks = get_docs_service()
        node = ks.register_document(library_id=library_id, file_path=file_path, doc_id=doc_id)
        return node.id

    def create_parse_task(
        self,
        library_id: str,
        doc_id: str,
        file_path: str,
        parse_options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """创建解析任务并启动后台线程。"""
        ks = get_docs_service()
        task_id = f"parse-{uuid.uuid4().hex[:12]}"
        task = ks.create_parse_task(task_id, library_id, doc_id)
        arrival_seq = next(self._arrival_counter)
        ks.update_node(
            doc_id,
            status="processing",
            parse_progress=0,
            parse_stage="queued",
            parse_error=None,
            parse_task_id=task_id,
        )
        # 记录表同步：API 层可注入自己的实现（处理 pending 占位改名等界面语义），
        # 不注入时用 docs-core 默认实现——脚本/进程内路径同样要有流水。
        self._sync_record(task_id, doc_id, "processing")

        worker = threading.Thread(
            target=self._run_parse_task,
            args=(task_id, library_id, doc_id, file_path, parse_options or {}, arrival_seq),
            daemon=True,
            name=f"parse-task-{task_id}",
        )
        self._threads[task_id] = worker
        self._parsers[task_id] = MinerUParser()
        worker.start()
        return {
            "task_id": task.id,
            "doc_id": doc_id,
            "status": task.status,
            "progress": task.progress,
            "stage": task.stage,
        }

    def get_parse_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """返回当前任务状态。"""
        ks = get_docs_service()
        task = ks.get_parse_task(task_id)
        if not task:
            return None
        return task.model_dump(mode="json")

    def cancel_parse_task(self, task_id: str) -> bool:
        """取消正在运行的解析任务。"""
        ks = get_docs_service()
        task = ks.get_parse_task(task_id)
        if not task:
            return False
        if task.status in ("completed", "failed", "cancelled"):
            return False
        requested = ks.request_parse_task_cancel(task_id)
        if not requested:
            return False
        ks.update_node(
            task.doc_id,
            status="failed",
            parse_progress=100,
            parse_stage="cancelled",
            parse_error="用户手动取消任务",
            parse_task_id=task_id,
        )
        self._sync_record(task_id, task.doc_id, "cancelled", "用户手动取消任务")
        self._cancelled.add(task_id)
        parser = self._parsers.get(task_id)
        if parser:
            parser.cancel()
        return True

    def retry_parse_task(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """重试解析任务（支持已完成、失败、取消、待处理状态的文档重新解析）。"""
        ks = get_docs_service()
        node = ks.get_node(doc_id)
        if not node:
            return None
        if node.status == "processing":
            stale_task_id = str(getattr(node, "parse_task_id", None) or "").strip()
            thread = self._threads.get(stale_task_id) if stale_task_id else None
            if thread is not None and thread.is_alive():
                raise ValueError(f"节点 {doc_id} 正在解析中，请先取消当前任务")
            # 旧任务线程已死（进程重启/异常退出）：标记失败后允许重新解析，避免永久僵尸
            if stale_task_id:
                try:
                    ks.update_parse_task(
                        stale_task_id,
                        status="failed",
                        progress=100,
                        stage="failed",
                        stage_message="旧任务已中断，允许重新解析",
                        error="旧任务已中断",
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("标记旧解析任务失败 task=%s: %s", stale_task_id, exc)
                self._threads.pop(stale_task_id, None)
                self._parsers.pop(stale_task_id, None)
        file_path = node.file_path
        if not file_path:
            raise ValueError(f"节点 {doc_id} 缺少文件路径信息")
        # resume 语义（2026-09-15）：raw_parse(MinerU) 已完成的文档（典型 = 部署重启打断，
        # 启动自愈只标 failed 不重排，12 篇积压实踩）只补未完成阶段，复用 GPU 产物；
        # 阶段全终态仍挂着 failed（自愈误盖章）→ 按阶段记录把状态同步正，一次任务都不建；
        # 无阶段记录 / raw_parse 未完成 → 维持旧的全量重跑。
        stage_rows = list(ks.meta_store.list_parse_stages(doc_id))
        raw_done = any(
            str(r.get("stage") or "") == "raw_parse" and str(r.get("status") or "") == "completed"
            for r in stage_rows)
        if raw_done:
            remaining = compute_resume_stages("all", stage_rows)
            if not remaining:
                return self._sync_terminal_from_stage_records(doc_id, stage_rows)
            return self.create_parse_task(
                library_id=node.library_id, doc_id=doc_id, file_path=file_path,
                parse_options={"stages": remaining},
            )
        return self.create_parse_task(
            library_id=node.library_id,
            doc_id=doc_id,
            file_path=file_path,
        )

    def _sync_terminal_from_stage_records(self, doc_id: str, stage_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        """resume 发现无剩余阶段：按阶段记录推导整体状态，同步 node/task/parse_record。

        场景 = 启动自愈把「其实只差图描述/已全部完成」的任务盖章 failed；
        直接同步比空跑一遍流水线更快也更准（不会再消耗 GPU/VLM）。"""
        ks = get_docs_service()
        stage_status = {str(r.get("stage") or ""): str(r.get("status") or "")
                        for r in stage_rows if r.get("stage")}
        dep_skipped = {str(r.get("stage") or "") for r in stage_rows
                       if str(r.get("status") or "") == "skipped" and is_dependency_skip_message(r.get("message"))}
        overall = derive_overall_status(stage_status, dependency_skipped=dep_skipped)
        node = ks.get_node(doc_id)
        library_id = str(getattr(node, "library_id", "") or "") if node else ""
        parse_error: Optional[str] = None
        if overall in ("failed", "partial"):
            parts = [
                f"{r.get('stage')}: {str(r.get('error')).splitlines()[0]}"
                for r in stage_rows
                if str(r.get("status") or "") == "failed" and r.get("error")
            ]
            parse_error = "; ".join(parts[:3]) or overall
        old_task_id = str(getattr(node, "parse_task_id", None) or "").strip() if node else ""
        if old_task_id and not old_task_id.startswith("pending-"):
            try:
                ks.update_parse_task(old_task_id, status=overall, progress=100, stage=overall,
                                     stage_message="重试：无剩余阶段，按阶段记录同步状态")
            except Exception as exc:  # noqa: BLE001
                logger.warning("按阶段记录同步任务状态失败 task=%s: %s", old_task_id, exc)
        ks.update_node(doc_id, status=overall, parse_progress=100, parse_stage=overall,
                       parse_error=parse_error)
        self._sync_record(old_task_id, doc_id, overall, parse_error)
        if overall in ("completed", "partial"):
            try:
                from docs_core.step09_query.doc_search import catalog_write_enabled, refresh_doc_semantics

                if catalog_write_enabled():
                    refresh_doc_semantics(library_id, doc_id)
            except Exception as exc:  # noqa: BLE001 —— 目录刷新失败不影响解析结果
                logger.warning("目录语义刷新失败 doc=%s: %s", doc_id, exc)
        return {"task_id": old_task_id, "status": overall, "synced": True}

    def _run_parse_task(
        self,
        task_id: str,
        library_id: str,
        doc_id: str,
        file_path: str,
        parse_options: Dict[str, Any],
        arrival_seq: int = 1,
    ) -> None:
        """在后台执行文档解析：驱动阶段化管线并同步总体状态。"""
        ks = get_docs_service()
        meta_store = ks.meta_store
        stage_filter = parse_options.get("stages", "all")
        # 单阶段启动的输入提示：源文件路径（convert/raw_parse 的输入 = 上一步 source_prep 的内容）
        node = ks.get_node(doc_id)
        input_hint = node.file_path if node else None
        # 全量解析清空全部阶段；单阶段启动只重置目标阶段，保留其他阶段状态
        if stage_filter == "all":
            reset_parse_stage_records(meta_store, doc_id)
        else:
            for s in (stage_filter if isinstance(stage_filter, list) else [stage_filter]):
                meta_store.upsert_parse_stage(doc_id, s, status="pending", message="", error="",
                                              input_summary=input_hint or "")
        ctx = StageContext(
            task_id=task_id, library_id=library_id, doc_id=doc_id,
            file_path=file_path, parse_options=parse_options,
            task_parser=self._parsers.get(task_id),
            arrival_seq=arrival_seq,
        )
        ctx.sync_record = self._sync_record

        def _on_stage_update(stage_key, results):
            overall = derive_overall_status(dict(results))
            self._update_progress(task_id, doc_id, status=overall, stage=stage_key,
                                  stage_message=f"阶段 {stage_key} 完成", progress=0)

        try:
            results = run_pipeline(
                ctx, stage_filter,
                meta_store=meta_store,
                on_stage_update=_on_stage_update,
                raise_if_cancelled=lambda: self._raise_if_cancel_requested(task_id),
            )
            # 单阶段启动：最终状态由本次实际运行的阶段决定，避免误判 processing
            if stage_filter == "all":
                overall = derive_overall_status(results)
            else:
                existing_rows = list(meta_store.list_parse_stages(doc_id))
                existing = {
                    str(s.get("stage") or ""): str(s.get("status") or "")
                    for s in existing_rows
                }
                # 部分阶段运行的合法形态（v1 API stages 子集等）：本次未启动且无历史记录的阶段
                # 视为 skipped，不阻塞整体完成判定。修复 v1 API 默认 stages=structure 子集运行
                # 永远停在 processing 的问题（2026-09-11 OmniDocBench 接入实踩）。
                for _stage_key in STAGE_REGISTRY:
                    if _stage_key not in existing and _stage_key not in (results or {}):
                        existing[_stage_key] = "skipped"
                overall = derive_merged_overall_status(
                    existing,
                    results,
                    dependency_skipped={
                        str(s.get("stage") or "")
                        for s in existing_rows
                        if str(s.get("status") or "") == "skipped"
                        and is_dependency_skip_message(s.get("message"))
                    },
                )
            missing_artifacts: List[str] = []
            if overall == "completed":
                missing_artifacts = _missing_core_artifacts(library_id, doc_id)
                if missing_artifacts:
                    overall = "partial"
            degraded_note = ""
            try:
                from docs_core.step06_vectors.embedding_provider import default_embedding_provider

                if "embedding_hash_fallback" in list(getattr(default_embedding_provider, "runtime_flags", []) or []):
                    degraded_note = "embedding 已降级为 hash（向量检索质量下降，请检查 embedding 服务）"
            except Exception:  # noqa: BLE001
                pass
            ks.update_parse_task(task_id, status=overall, progress=100, stage=overall,
                                 stage_message=f"解析结束: {overall}" + (f"；⚠ {degraded_note}" if degraded_note else ""))
            parse_error = ""
            if overall in ("failed", "partial"):
                failed_stages = [
                    s for s in meta_store.list_parse_stages(doc_id)
                    if s.get("status") == "failed" and s.get("error")
                ]
                parse_error = "; ".join(
                    f"{s.get('stage')}: {str(s.get('error')).splitlines()[0]}"
                    for s in failed_stages[:3]
                ) or overall
                if missing_artifacts:
                    parse_error += "；缺少核心结构产物: " + ", ".join(missing_artifacts)
            ks.update_node(doc_id, status=overall, parse_progress=100, parse_stage=overall,
                           parse_error=parse_error or None, parse_task_id=task_id)
            self._sync_record(task_id, doc_id, overall, degraded_note or None)
            if overall in ("completed", "partial"):
                try:
                    from docs_core.step09_query.doc_search import catalog_write_enabled, refresh_doc_semantics

                    if catalog_write_enabled():
                        refresh_doc_semantics(library_id, doc_id)
                except Exception as exc:  # noqa: BLE001 —— 目录刷新失败不影响解析结果
                    logger.warning("目录语义刷新失败 doc=%s: %s", doc_id, exc)
        except ParseTaskCancelledError as exc:
            error_message = str(exc) or "用户手动取消任务"
            ks.update_parse_task(
                task_id,
                status="cancelled",
                progress=100,
                stage="cancelled",
                stage_message=error_message,
                error=error_message,
            )
            ks.update_node(
                doc_id,
                status="failed",
                parse_progress=100,
                parse_stage="cancelled",
                parse_error=error_message,
                parse_task_id=task_id,
            )
            self._sync_record(task_id, doc_id, "cancelled", error_message)
        except Exception as exc:
            if task_id in self._cancelled:
                self._sync_record(task_id, doc_id, "cancelled", "用户手动取消任务")
                ks.update_node(doc_id, status="failed", parse_stage="cancelled", parse_error="用户手动取消任务")
                try:
                    ks.update_parse_task(task_id, status="cancelled")
                except Exception:
                    pass
                return
            error_message = f"{type(exc).__name__}: {exc}"
            error_detail = traceback.format_exc()
            logger.error(f"解析任务 {task_id} 失败: {error_message}\n{error_detail}")
            try:
                ks.update_parse_task(
                    task_id,
                    status="failed",
                    progress=100,
                    stage="failed",
                    stage_message=error_message,
                    error=error_message,
                )
                ks.update_node(
                    doc_id,
                    status="failed",
                    parse_progress=100,
                    parse_stage="failed",
                    parse_error=error_message,
                    parse_task_id=task_id,
                )
                self._sync_record(task_id, doc_id, "failed", error_message)
            except Exception as update_exc:
                logger.error(f"更新任务状态失败: {update_exc}")
        finally:
            # 任务在获槽前退出时作废其排队号（退出兜底）。新语义（按到达排队）下
            # 未到达闸门的任务不占排位，此调用对它们是空操作；但三个闸门仍须补齐：
            # 到达过闸门又未获槽的残余场景漏一个 skip，就会把该闸门队首永久卡住
            # （图描述闸门曾因漏 skip 而假死）。
            _MINERU_GPU_GATE.skip(arrival_seq)
            for _g in _ENDPOINT_GATES.values():
                _g.skip(arrival_seq)
            _POPO_GATE.skip(arrival_seq)
            _FTS_GATE.skip(arrival_seq)
            _FIGURE_DESCRIBE_GATE.skip(arrival_seq)
            _CONVERT_GATE.skip(arrival_seq)
            self._threads.pop(task_id, None)
            self._cancelled.discard(task_id)
            parser = self._parsers.pop(task_id, None)
            if parser:
                parser.cancel()

    def _update_progress(
        self,
        task_id: str,
        doc_id: str,
        progress: int,
        stage: str,
        status: str = "processing",
        stage_message: Optional[str] = None,
    ) -> None:
        """同步更新任务和节点的解析进度。"""
        ks = get_docs_service()
        ks.update_parse_task(
            task_id,
            status=status,
            progress=progress,
            stage=stage,
            stage_message=stage_message,
            error=None,
        )
        ks.log_parse_step(task_id, doc_id, stage, progress, stage_message)
        ks.update_node(
            doc_id,
            status="completed" if status == "completed" else "processing",
            parse_progress=progress,
            parse_stage=stage,
            parse_error=None,
            parse_task_id=task_id,
        )

    def _raise_if_cancel_requested(self, task_id: str) -> None:
        """在阶段边界/阶段内部取消点检查用户是否请求取消任务（内存标志，无数据库竞态）。"""
        if task_id in self._cancelled:
            raise ParseTaskCancelledError("用户手动取消任务")
