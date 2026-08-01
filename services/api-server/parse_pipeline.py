"""文档解析阶段化管线：阶段注册表 + 依赖排序 + 状态派生 + 运行器。

设计约定：
- 每个阶段是 {key, title, kind(hard/soft), depends_on, run(ctx)} 的注册项；
- hard 阶段失败 → 终止后续阶段；soft 阶段失败 → 仅标记自身 failed，继续后续；
- 阶段状态通过 meta_store.upsert_parse_stage 持久化（doc_parse_stages 表）。
"""
import logging
import os
import shutil
import subprocess
import tempfile
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

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


@dataclass
class StageDef:
    key: str
    title: str
    kind: str
    depends_on: List[str]
    run: Callable[["StageContext"], str]
    verify: Optional[Callable[["StageContext"], str]] = None


# ---- 阶段输入核查（启动前先核查输入，通过后通知前端「核查通过」再运行） ----

def _verify_source_file(ctx: StageContext) -> str:
    if not Path(ctx.file_path).is_file():
        raise RuntimeError(f"源文件不存在: {ctx.file_path}")
    ctx.input_summary = ctx.file_path
    return "核查通过"


def _verify_convert_input(ctx: StageContext) -> str:
    from docs_core.read.convert.pdf_converter import prepare_source

    if not ctx.source_path:
        ctx.source_path = prepare_source(ctx.library_id, ctx.doc_id, ctx.file_path)
    if not Path(ctx.source_path).is_file():
        raise RuntimeError(f"源文件不存在: {ctx.source_path}")
    ctx.input_summary = ctx.source_path
    return "核查通过"


def _verify_raw_parse_input(ctx: StageContext) -> str:
    """MinerU 输入必须是 PDF（convert 转换后或上传即 PDF）。"""
    from docs_core.read.convert.pdf_converter import resolve_pdf_input

    ctx.source_path = resolve_pdf_input(ctx.library_id, ctx.doc_id)
    if not Path(ctx.source_path).is_file():
        raise RuntimeError(f"PDF 输入文件不存在: {ctx.source_path}")
    ctx.input_summary = ctx.source_path
    return "核查通过"


def _verify_mineru_raw_input(ctx: StageContext) -> str:
    from docs_core.write.store.assets_file_store import file_storage

    mineru_raw_dir = file_storage.get_mineru_raw_dir(ctx.library_id, ctx.doc_id)
    if not mineru_raw_dir.exists():
        raise RuntimeError(f"输入目录不存在: {mineru_raw_dir}")
    ctx.input_summary = str(mineru_raw_dir)
    return "核查通过"


def _verify_doc_blocks_graph_input(ctx: StageContext) -> str:
    from docs_core.write.store.assets_file_store import file_storage

    # 结构产物以 jsonl+meta 为主（Solo/PoPo 均产出），legacy 单文件兜底
    graph_path = file_storage.get_graph_jsonl_path(ctx.library_id, ctx.doc_id)
    if not graph_path.exists():
        graph_path = file_storage.get_parsed_dir(ctx.library_id, ctx.doc_id) / "doc_blocks_graph.json"
    if not graph_path.exists():
        raise RuntimeError(f"输入文件不存在: {graph_path}")
    ctx.input_summary = str(graph_path)
    return "核查通过"


# ---- 阶段执行函数 ----

def _run_source_prep(ctx: StageContext) -> str:
    from docs_core.read.convert.pdf_converter import prepare_source

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

    from docs_core.read.convert.pdf_converter import convert_to_pdf

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

    try:
        # 解析器自建临时目录并负责落盘（save_markdown + save_parse_artifacts）
        parse_result = task_parser.parse_to_raw_artifacts(
            input_path=ctx.source_path,
            library_id=ctx.library_id,
            doc_id=ctx.doc_id,
        )
    except Exception as exc:
        # MinerU 解析被取消（_abort_event 已设置）：转成取消异常，向上传播为 cancelled
        if getattr(task_parser, "_abort_event", None) is not None and task_parser._abort_event.is_set():
            raise ParseTaskCancelledError("用户手动取消任务") from exc
        raise
    if not parse_result.get("success"):
        raise RuntimeError(parse_result.get("error") or "MinerU解析失败")

    persisted = parse_result.get("persisted") or {}
    ctx.input_summary = ctx.source_path
    ctx.output_summary = persisted.get("output_summary") or ""
    has_images = bool(persisted.get("has_images"))
    backend = getattr(ctx.task_parser, "backend", None) or os.environ.get("MINERU_BACKEND", "hybrid-engine")
    return f"MinerU解析完成||{backend}||{'' if has_images else '（无图片资源）'}"


def _run_popo(ctx: StageContext) -> str:
    normalizer_backend = os.environ.get("DOCS_CORE_NORMALIZER_BACKEND", "legacy")
    if normalizer_backend != "popo":
        return "__skipped__:未启用（DOCS_CORE_NORMALIZER_BACKEND != popo）"

    from docs_core.read.normalize.popo import get_popo_pipeline
    from docs_core.read.normalize.popo import po_po_blocks_to_canonical
    from docs_core.read.normalize.popo import run_popo_projection
    from docs_core.read.organize.builder import build_canonical_document_from_popoblocks
    from docs_core.write.store.assets_file_store import file_storage
    from docs_core.knowledge_service import get_knowledge_service

    ks = get_knowledge_service()
    mineru_raw_dir = file_storage.get_mineru_raw_dir(ctx.library_id, ctx.doc_id)
    if not mineru_raw_dir.exists():
        raise FileNotFoundError(f"mineru_raw_dir not found at {mineru_raw_dir}")

    popo_output_dir = str(file_storage.get_popo_dir(ctx.library_id, ctx.doc_id))
    pipeline = get_popo_pipeline()
    # PDF 源在 source 目录（转换后的 PDF 或上传的 PDF），重试/resume 时 ctx.source_path 可能为空，兜底解析
    source_pdf = str(ctx.source_path or "")
    if not source_pdf:
        source_dir = file_storage.get_source_dir(ctx.library_id, ctx.doc_id)
        pdfs = sorted(source_dir.glob("*.pdf"))
        if pdfs:
            source_pdf = str(pdfs[-1])
    try:
        pipeline.run_full_pipeline(
            mineru_raw_dir=str(mineru_raw_dir),
            output_dir=popo_output_dir,
            doc_id=ctx.doc_id,
            source_pdf_path=source_pdf,
        )
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        stdout = (exc.stdout or "").strip()
        detail = stderr or stdout or str(exc)
        raise RuntimeError(f"PoPo 子进程失败:\n{detail}") from exc

    enriched_blocks = file_storage.read_popo_enriched_blocks(ctx.library_id, ctx.doc_id)
    document_tree = file_storage.read_popo_document_tree(ctx.library_id, ctx.doc_id)
    blocks, outlines, id_map = po_po_blocks_to_canonical(ctx.doc_id, enriched_blocks, document_tree)

    mineru_md_path = mineru_raw_dir / "content.md"
    mineru_content_md = ""
    if mineru_md_path.exists():
        mineru_content_md = mineru_md_path.read_text(encoding="utf-8")

    parsed_dir = file_storage.get_parsed_dir(ctx.library_id, ctx.doc_id)
    content_md_output = str(parsed_dir / "content.md")
    graph_output = str(parsed_dir / "doc_blocks_graph.json")

    projection = run_popo_projection(
        library_id=ctx.library_id,
        doc_id=ctx.doc_id,
        blocks=blocks,
        outlines=outlines,
        mineru_content_md=mineru_content_md,
        graph_output_path=graph_output,
        content_md_output_path=content_md_output,
    )

    ks.clear_document_segments(ctx.doc_id)
    ks.save_document_segments(
        ctx.doc_id, ctx.library_id, "doc_blocks_graph_v1", projection["segments"],
    )

    doc_title = file_storage.get_doc_manifest(ctx.library_id, ctx.doc_id).get("title", ctx.doc_id)
    canonical_doc = build_canonical_document_from_popoblocks(
        library_id=ctx.library_id, doc_id=ctx.doc_id, title=doc_title,
        blocks=blocks, outlines=outlines,
    )
    ks.save_canonical_document_bare(canonical_doc)
    file_storage.save_middle_json(ctx.library_id, ctx.doc_id, canonical_doc.model_dump(mode="json"))

    from docs_core.write.store.blocks_sql_store import KnowledgeIndexStore, resolve_knowledge_index_db_path
    index_store = KnowledgeIndexStore(
        db_path=resolve_knowledge_index_db_path(), schema_version="1.0.0",
    )
    index_store.clear_doc_blocks(ctx.doc_id)
    index_store.insert_doc_blocks_base_rows(projection["base_rows"])

    ctx.popo_ran = True
    ctx.input_summary = str(mineru_raw_dir)
    ctx.output_summary = f"{popo_output_dir} + {parsed_dir}/content.md + {parsed_dir}/doc_blocks_graph.json"
    return f"PoPo 完成，{len(blocks)} blocks，{len(outlines)} outlines"


def _run_structure(ctx: StageContext) -> str:
    if ctx.popo_ran:
        return "__skipped__:PoPo 已完成结构化"

    from docs_core.write.store.assets_file_store import build_structured_index_for_doc

    use_llm = bool(ctx.parse_options.get("use_llm", True))
    llm_model = str(ctx.parse_options.get("llm_model") or "").strip() or None
    result = build_structured_index_for_doc(
        library_id=ctx.library_id,
        doc_id=ctx.doc_id,
        strategy="doc_blocks_graph_v1",
        options={
            "use_llm": use_llm,
            "llm_model": llm_model,
        },
    )
    stats = result.get("stats", {})
    from docs_core.write.store.assets_file_store import file_storage
    ctx.input_summary = str(file_storage.get_mineru_raw_dir(ctx.library_id, ctx.doc_id))
    ctx.output_summary = str(file_storage.get_parsed_dir(ctx.library_id, ctx.doc_id))
    return f"结构化完成，{stats.get('canonical_blocks_count', 0)} blocks"


def _run_fts(ctx: StageContext) -> str:
    from docs_core.knowledge_service import get_knowledge_service

    ks = get_knowledge_service()
    ks.canonical_store.rebuild_chunk_fts(ctx.doc_id)
    ctx.input_summary = ctx.doc_id
    ctx.output_summary = "canonical_chunk_fts (FTS5 table)"
    return "FTS 重建完成"


def _run_vectors(ctx: StageContext) -> str:
    from docs_core.knowledge_service import get_knowledge_service
    from docs_core.write.indexing.embedding_provider import default_embedding_provider

    ks = get_knowledge_service()
    ks.rebuild_document_vectors(ctx.doc_id)
    ctx.input_summary = ctx.doc_id
    ctx.output_summary = "vector store (entity_id + embedding)"

    flags = getattr(default_embedding_provider, "runtime_flags", [])
    if "embedding_hash_fallback" in flags:
        return "向量索引完成（degraded: embedding_hash_fallback）"

    return "向量索引完成"


def _run_graph(ctx: StageContext) -> str:
    from docs_core.knowledge_service import push_to_graph

    result = push_to_graph(ctx.library_id, ctx.doc_id)
    if not result.get("pushed"):
        error = result.get("error", "未知错误")
        raise RuntimeError(f"图谱构建失败: {error}")

    from docs_core.write.store.assets_file_store import file_storage
    ctx.input_summary = str(file_storage.get_parsed_dir(ctx.library_id, ctx.doc_id) / "doc_blocks_graph.json")
    ctx.output_summary = "knowledge_graph.sqlite (entities + relations)"

    entities = result.get("entities_count", 0)
    relations = result.get("relations_count", 0)
    return f"图谱完成，{entities} 实体，{relations} 关系"


STAGE_REGISTRY: Dict[str, StageDef] = {s.key: s for s in [
    StageDef("source_prep", "源文件准备", STAGE_KIND_HARD, [], _run_source_prep, _verify_source_file),
    StageDef("convert", "格式转换", STAGE_KIND_HARD, ["source_prep"], _run_convert, _verify_convert_input),
    StageDef("raw_parse", "MinerU解析", STAGE_KIND_HARD, ["convert"], _run_raw_parse, _verify_raw_parse_input),
    StageDef("popo", "PoPo 强化", STAGE_KIND_SOFT, ["raw_parse"], _run_popo, _verify_mineru_raw_input),
    StageDef("structure", "Solo 强化", STAGE_KIND_HARD, ["raw_parse"], _run_structure, _verify_mineru_raw_input),
    StageDef("fts", "全文索引", STAGE_KIND_HARD, ["structure"], _run_fts, _verify_doc_blocks_graph_input),
    StageDef("vectors", "向量索引", STAGE_KIND_SOFT, ["structure"], _run_vectors, _verify_doc_blocks_graph_input),
    StageDef("graph", "知识图谱", STAGE_KIND_SOFT, ["structure"], _run_graph, _verify_doc_blocks_graph_input),
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
        started = datetime.now().isoformat()
        meta_store.upsert_parse_stage(ctx.doc_id, key, status="running", started_at=started)
        t0 = time.time()
        ctx.input_summary = ""
        ctx.output_summary = ""
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
            meta_store.upsert_parse_stage(
                ctx.doc_id, key, status="failed",
                error=error_message + "\n" + traceback.format_exc(limit=3),
                started_at=started, finished_at=datetime.now().isoformat(),
            )
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
