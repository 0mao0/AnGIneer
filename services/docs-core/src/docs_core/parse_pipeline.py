"""文档解析阶段化管线：阶段注册表 + 依赖排序 + 状态派生 + 运行器 + 任务编排器。

设计约定：
- 每个阶段是 {key, title, kind(hard/soft), depends_on, run(ctx)} 的注册项；
- hard 阶段失败 → 终止后续阶段；soft 阶段失败 → 仅标记自身 failed，继续后续；
- 阶段状态通过 meta_store.upsert_parse_stage 持久化（doc_parse_stages 表）。
- ParseOrchestrator：创建/取消/重试解析任务，在后台线程驱动本管线并同步状态。
"""
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
from typing import Any, Callable, Dict, List, Optional

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
    cancel_check: Optional[Callable[[], None]] = None
    fallback_target: Optional[str] = None
    stage_key: Optional[str] = None
    steps: List[Dict[str, Any]] = field(default_factory=list)
    sync_record: Optional[Callable[[str, str, str], None]] = None
    arrival_seq: int = 1

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
    if not Path(ctx.file_path).is_file():
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

    def _mark_queued() -> None:
        """排队等待 GPU：阶段/任务/解析记录状态同步为排队中，避免误显示解析耗时。"""
        ctx.log_step("MinerU GPU 排队", "running", "等待 MinerU GPU 资源（前序任务完成后自动开始）")
        if ctx.meta_store is not None and ctx.stage_key:
            ctx.meta_store.upsert_parse_stage(
                ctx.doc_id, ctx.stage_key, status="queued",
                message="等待 MinerU GPU 资源",
                started_at=ctx.stage_started_at or datetime.now().isoformat(),
            )
        try:
            get_docs_service().update_parse_task(
                ctx.task_id, stage="queued", stage_message="等待 MinerU GPU 资源"
            )
            if ctx.sync_record is not None:
                ctx.sync_record(ctx.task_id, ctx.doc_id, "queued")
        except Exception as exc:
            logger.warning("排队状态同步失败 task=%s: %s", ctx.task_id, exc)

    def _mark_parsing() -> None:
        """拿到 GPU 槽位：阶段计时从此刻重新开始，排队等待不计入解析耗时。"""
        if ctx.meta_store is not None and ctx.stage_key:
            ctx.meta_store.upsert_parse_stage(
                ctx.doc_id, ctx.stage_key, status="running",
                message="核查通过",
                started_at=datetime.now().isoformat(),
            )
        try:
            get_docs_service().update_parse_task(
                ctx.task_id, stage="raw_parse", stage_message="MinerU 解析中"
            )
            if ctx.sync_record is not None:
                ctx.sync_record(ctx.task_id, ctx.doc_id, "processing")
        except Exception as exc:
            logger.warning("解析状态同步失败 task=%s: %s", ctx.task_id, exc)

    if _MINERU_GPU_GATE.should_wait(ctx.arrival_seq):
        _mark_queued()
    with mineru_gpu_slot(ctx.cancel_check, arrival_seq=ctx.arrival_seq):
        _mark_parsing()
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

    def _on_step(step: str, status: str = "done", detail: str = "") -> None:
        ctx.log_step(step, status, detail)

    # PDF 源在 source 目录（转换后的 PDF 或上传的 PDF），重试/resume 时 ctx.source_path 可能为空，兜底解析
    source_pdf = str(ctx.source_path or "")
    if not source_pdf:
        pdfs = sorted(source_dir.glob("*.pdf"))
        if pdfs:
            source_pdf = str(pdfs[-1])
    try:
        pipeline.run_full_pipeline(
            mineru_raw_dir=str(mineru_raw_dir),
            output_dir=popo_output_dir,
            doc_id=ctx.doc_id,
            source_pdf_path=source_pdf,
            source_dir=str(source_dir),
            on_step=_on_step,
        )
    except Exception as exc:
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
    return f"结构化完成（solo 降级），{stats.get('nodes_count', 0)} blocks"


def _run_fts(ctx: StageContext) -> str:
    import docs_core.paths as paths
    from docs_core.step05_sqlite_fts.sqlite_index import build_sqlite_index_from_graph

    result = build_sqlite_index_from_graph(ctx.library_id, ctx.doc_id)
    ctx.input_summary = str(paths.get_graph_jsonl_path(ctx.library_id, ctx.doc_id))
    ctx.output_summary = (
        f"canonical SQLite + doc_blocks + segments + canonical_chunk_fts "
        f"({result.get('canonical_blocks_count', 0)} blocks)"
    )
    return f"SQLite 建库完成，FTS 重建完成（{result.get('canonical_blocks_count', 0)} blocks）"


# ---- MinerU/GPU 并发闸门：同一时刻最多一个 MinerU 任务占用 GPU ----
class _FifoGpuGate:
    """进程级 FIFO GPU 闸门：按提交序号（arrival_seq）严格先来先服务。

    即使 GPU 空闲，序号靠后的任务也必须等序号靠前的任务先获得（或排队期间
    被取消并让位），确保“谁先提交谁先用资源”，不受前序阶段（source_prep /
    convert）完成速度影响。排队期间被取消的序号会被跳过，避免后续任务永久等待。
    """

    def __init__(self, max_concurrency: int = 1) -> None:
        self._max_concurrency = max(1, int(max_concurrency))
        self._cond = threading.Condition()
        self._tokens = self._max_concurrency
        self._next_seq = 1
        self._cancelled_seqs: set[int] = set()

    @property
    def available(self) -> int:
        """当前空闲令牌数（仅用于排队提示）。"""
        with self._cond:
            return self._tokens

    def _skip_cancelled_locked(self) -> None:
        """跳过排队期间被取消的序号，避免后续任务永久等待。"""
        while self._next_seq in self._cancelled_seqs:
            self._cancelled_seqs.discard(self._next_seq)
            self._next_seq += 1

    def should_wait(self, seq: int) -> bool:
        """该序号是否还需要排队（用于 queued 状态提示）。"""
        with self._cond:
            return seq != self._next_seq or self._tokens <= 0

    def skip(self, seq: int) -> None:
        """跳过在到达闸门前就失败/退出的序号，避免后续任务永久等待。

        已经获得槽位的任务（seq < next_seq）调用此方法为无操作，
        避免重复推进队列。
        """
        with self._cond:
            if seq >= self._next_seq:
                self._cancelled_seqs.add(seq)
                self._skip_cancelled_locked()
                self._cond.notify_all()

    def acquire(
        self,
        seq: int,
        cancel_check: Optional[Callable[[], None]] = None,
        poll_interval: float = 0.5,
    ) -> None:
        """按提交序号阻塞等待令牌；等待期间按 poll_interval 轮询取消标志。"""
        with self._cond:
            while True:
                if seq == self._next_seq and self._tokens > 0:
                    self._tokens -= 1
                    self._next_seq += 1
                    self._skip_cancelled_locked()
                    self._cond.notify_all()
                    return
                if seq < self._next_seq and self._tokens > 0:
                    # 晚到/重复序号兜底：不取消任务，等待到空闲令牌后直接放行。
                    # 正常情况下不应发生；发生时不阻塞队列推进，也不误伤任务。
                    logger.warning(
                        "GPU 闸门兜底放行（晚到序号）: seq=%s next_seq=%s tokens=%s pid=%s",
                        seq, self._next_seq, self._tokens, os.getpid(),
                    )
                    self._tokens -= 1
                    return
                if cancel_check is not None:
                    try:
                        cancel_check()  # 取消时抛 ParseTaskCancelledError，不消费令牌
                    except BaseException:
                        # 排队期间被取消：登记序号并让位给后续任务
                        self._cancelled_seqs.add(seq)
                        if seq >= self._next_seq:
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
    """MinerU 任务占用的 GPU 槽位：按提交序号先来先服务，进入 raw_parse 前获取。"""
    _MINERU_GPU_GATE.acquire(arrival_seq, cancel_check)
    try:
        yield
    finally:
        _MINERU_GPU_GATE.release()


def _run_vectors(ctx: StageContext) -> str:
    from docs_core.docs_service import get_docs_service
    from docs_core.step06_vectors.embedding_provider import default_embedding_provider

    ks = get_docs_service()
    ks.rebuild_document_vectors(ctx.doc_id)
    ctx.input_summary = ctx.doc_id
    ctx.output_summary = "vector store (entity_id + embedding)"

    flags = getattr(default_embedding_provider, "runtime_flags", [])
    if "embedding_hash_fallback" in flags:
        return "向量索引完成（degraded: embedding_hash_fallback）"

    return "向量索引完成"


def _run_graph(ctx: StageContext) -> str:
    from docs_core.step07_graph.push_to_graph import push_to_graph

    result = push_to_graph(ctx.library_id, ctx.doc_id)
    if not result.get("pushed"):
        error = result.get("error", "未知错误")
        raise RuntimeError(f"图谱构建失败: {error}")

    import docs_core.paths as paths
    ctx.input_summary = str(paths.get_graph_jsonl_path(ctx.library_id, ctx.doc_id))
    ctx.output_summary = "knowledge_graph.sqlite (entities + relations)"

    entities = result.get("entities_count", 0)
    relations = result.get("relations_count", 0)
    return f"图谱完成，{entities} 实体，{relations} 关系"


STAGE_REGISTRY: Dict[str, StageDef] = {s.key: s for s in [
    StageDef("source_prep", "1 源文件准备", STAGE_KIND_HARD, [], _run_source_prep, _verify_source_file, step="1"),
    StageDef("convert", "2 格式转换", STAGE_KIND_HARD, ["source_prep"], _run_convert, _verify_convert_input, step="2"),
    StageDef("raw_parse", "3.1 MinerU解析", STAGE_KIND_HARD, ["convert"], _run_raw_parse, _verify_raw_parse_input, step="3.1"),
    StageDef("popo", "3.2 PoPo强化", STAGE_KIND_SOFT, ["raw_parse"], _run_popo, _verify_mineru_raw_input, step="3.2"),
    StageDef("structure", "4 结构化（Solo 唯一构建者）", STAGE_KIND_HARD, ["raw_parse"], _run_structure, _verify_mineru_raw_input, step="4"),
    StageDef("fts", "5 SQLite+FTS", STAGE_KIND_HARD, ["structure"], _run_fts, _verify_doc_blocks_graph_input, step="5"),
    StageDef("vectors", "6 向量索引", STAGE_KIND_SOFT, ["fts"], _run_vectors, _verify_doc_blocks_graph_input, step="6"),
    StageDef("graph", "7 知识图谱", STAGE_KIND_SOFT, ["structure"], _run_graph, _verify_doc_blocks_graph_input, step="7"),
]}

_PIPELINE_ORDER = [
    "source_prep", "convert", "raw_parse", "popo", "structure", "fts", "vectors", "graph",
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


def derive_overall_status(stage_status: Dict[str, str]) -> str:
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
    values = list(effective.values())
    if any(v == "failed" for v in values):
        return "partial"
    if all(effective.get(key) in ("completed", "skipped") for key in STAGE_REGISTRY):
        return "completed"
    return "processing"


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
        started = datetime.now().isoformat()
        meta_store.upsert_parse_stage(ctx.doc_id, key, status="running", started_at=started)
        t0 = time.time()
        ctx.input_summary = ""
        ctx.output_summary = ""
        ctx.stage_key = key
        ctx.steps = []
        ctx.meta_store = meta_store
        ctx.stage_started_at = started
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
                    finished_at=datetime.now().isoformat(),
                )
                continue
            results[key] = "completed"
            meta_store.upsert_parse_stage(
                ctx.doc_id, key, status="completed",
                message=f"{message}，耗时{round(time.time() - t0, 1)}s",
                started_at=started, finished_at=datetime.now().isoformat(),
                input_summary=ctx.input_summary, output_summary=ctx.output_summary,
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
                started_at=started, finished_at=datetime.now().isoformat(),
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
    ) -> None:
        """record_updater(task_id, doc_id, status, error)：可选，用于把任务状态同步到解析记录表。"""
        self._threads: Dict[str, threading.Thread] = {}
        self._parsers: Dict[str, MinerUParser] = {}
        self._cancelled: set = set()
        self._record_updater = record_updater
        self._arrival_counter = _GLOBAL_ARRIVAL_COUNTER

    def _sync_record(self, task_id: str, doc_id: str, status: str, error: Optional[str] = None) -> None:
        """把任务状态同步到解析记录表（由 API 层注入的实现负责）。"""
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
        # 记录表同步交给 API 层注入的钩子（docs_core 不依赖 api-server 模型）
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
            raise ValueError(f"节点 {doc_id} 正在解析中，请先取消当前任务")
        file_path = node.file_path
        if not file_path:
            raise ValueError(f"节点 {doc_id} 缺少文件路径信息")
        return self.create_parse_task(
            library_id=node.library_id,
            doc_id=doc_id,
            file_path=file_path,
        )

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
                keys = stage_filter if isinstance(stage_filter, list) else [stage_filter]
                statuses = [results.get(k) for k in keys]
                if any(s == "failed" for s in statuses):
                    overall = "failed"
                elif all(s in ("completed", "skipped") for s in statuses):
                    overall = "completed"
                else:
                    overall = "processing"
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
            ks.update_node(doc_id, status=overall, parse_progress=100, parse_stage=overall,
                           parse_error=parse_error or None, parse_task_id=task_id)
            self._sync_record(task_id, doc_id, overall, degraded_note or None)
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
            # 任务在到达 MinerU 闸门前就失败/退出时，跳过其序号，防止后续任务永久排队
            _MINERU_GPU_GATE.skip(arrival_seq)
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
