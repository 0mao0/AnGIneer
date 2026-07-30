"""文档解析阶段化管线：阶段注册表 + 依赖排序 + 状态派生 + 运行器。

设计约定：
- 每个阶段是 {key, title, kind(hard/soft), depends_on, run(ctx)} 的注册项；
- hard 阶段失败 → 终止后续阶段；soft 阶段失败 → 仅标记自身 failed，继续后续；
- 阶段状态通过 meta_store.upsert_parse_stage 持久化（doc_parse_stages 表）。
"""
import json
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


@dataclass
class StageDef:
    key: str
    title: str
    kind: str
    depends_on: List[str]
    run: Callable[["StageContext"], str]


# ---- 阶段执行函数 ----

def _run_source_prep(ctx: StageContext) -> str:
    from docs_core.write.store.assets_file_store import file_storage

    source_path = file_storage.ensure_doc_source_file(ctx.library_id, ctx.doc_id, file_path=ctx.file_path)
    if not source_path:
        raise RuntimeError("源文件不存在或无法复制到规范目录")
    ctx.source_path = source_path
    ctx.ext = Path(source_path).suffix.lower()
    return f"源文件就绪: {Path(source_path).name}"


def _run_convert(ctx: StageContext) -> str:
    if ctx.ext == ".pdf":
        return "__skipped__:PDF 输入，无需转换"

    from docs_core.read.convert.pdf_converter import convert_to_pdf
    from docs_core.write.store.assets_file_store import file_storage

    lo_dir = tempfile.mkdtemp(prefix=f"lo-{ctx.doc_id}-")
    try:
        source_path = convert_to_pdf(ctx.source_path, lo_dir)
        parsed_dir = file_storage.get_parsed_dir(ctx.library_id, ctx.doc_id)
        parsed_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(source_path), str(parsed_dir / "mineru_render.pdf"))
        ctx.source_path = source_path
        return f"LO 转换完成: {Path(source_path).name}"
    finally:
        shutil.rmtree(lo_dir, ignore_errors=True)


def _run_raw_parse(ctx: StageContext) -> str:
    from docs_core.write.store.assets_file_store import file_storage

    task_parser = ctx.task_parser
    if task_parser is None:
        raise RuntimeError("解析器不可用（任务已取消）")

    parse_result = task_parser.parse_to_raw_artifacts(input_path=ctx.source_path, output_dir=ctx.temp_output_dir)
    if not parse_result.get("success"):
        raise RuntimeError(parse_result.get("error") or "MinerU 解析失败")

    markdown_path = parse_result.get("md_file")
    if markdown_path:
        with open(markdown_path, "r", encoding="utf-8") as handle:
            file_storage.save_markdown(ctx.library_id, ctx.doc_id, handle.read())
    file_storage.save_parse_artifacts(ctx.library_id, ctx.doc_id, ctx.temp_output_dir)

    if ctx.ext != ".pdf":
        lo_pdf_path = file_storage.get_parsed_dir(ctx.library_id, ctx.doc_id) / "mineru_render.pdf"
        if not lo_pdf_path.exists():
            shutil.copy2(str(ctx.source_path), str(lo_pdf_path))

    return "MinerU 解析完成"


def _run_popo(ctx: StageContext) -> str:
    normalizer_backend = os.environ.get("DOCS_CORE_NORMALIZER_BACKEND", "legacy")
    if normalizer_backend != "popo":
        return "__skipped__:未启用（DOCS_CORE_NORMALIZER_BACKEND != popo）"

    from docs_core.read.normalize.popo_pipeline import get_popo_pipeline
    from docs_core.read.normalize.popo_mapper import po_po_blocks_to_canonical
    from docs_core.read.normalize.popo_projection import run_popo_projection
    from docs_core.read.organize.builder import build_canonical_document_from_popoblocks
    from docs_core.write.store.assets_file_store import file_storage
    from docs_core.knowledge_service import get_knowledge_service

    ks = get_knowledge_service()
    mineru_raw_dir = file_storage.get_mineru_raw_dir(ctx.library_id, ctx.doc_id)
    if not mineru_raw_dir.exists():
        raise FileNotFoundError(f"mineru_raw_dir not found at {mineru_raw_dir}")

    popo_output_dir = str(file_storage.get_popo_dir(ctx.library_id, ctx.doc_id))
    pipeline = get_popo_pipeline()
    source_pdf = str(file_storage.get_parsed_dir(ctx.library_id, ctx.doc_id) / "mineru_render.pdf")
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
    for row in projection["base_rows"]:
        index_store.insert_doc_block_row(row)

    ctx.popo_ran = True
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
    return f"结构化完成，{stats.get('canonical_blocks_count', 0)} blocks"


def _run_fts(ctx: StageContext) -> str:
    from docs_core.knowledge_service import get_knowledge_service

    ks = get_knowledge_service()
    ks.canonical_store.rebuild_chunk_fts(ctx.doc_id)
    return "FTS 重建完成"


def _run_vectors(ctx: StageContext) -> str:
    from docs_core.knowledge_service import get_knowledge_service
    from docs_core.write.indexing.embedding_provider import default_embedding_provider

    ks = get_knowledge_service()
    ks.rebuild_document_vectors(ctx.doc_id)

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

    entities = result.get("entities_count", 0)
    relations = result.get("relations_count", 0)
    return f"图谱完成，{entities} 实体，{relations} 关系"


def _run_sop(ctx: StageContext) -> str:
    from docs_core.write.graph.config import EntityLayer

    try:
        from sop_routes import _get_kg_store
    except ImportError:
        return "__skipped__:SOP 模块不可用"

    store = _get_kg_store()
    doc_entities = store.list_entities_by_doc(ctx.library_id, ctx.doc_id)
    if not doc_entities:
        return "__skipped__:该文档尚无图谱数据"

    frameworks = store.get_frameworks_by_doc(ctx.library_id, ctx.doc_id)
    action_entities = [e for e in doc_entities if e.layer == EntityLayer.ACTION]
    if not frameworks and not action_entities:
        return "__skipped__:图谱无 framework 或 action 实体"

    from sop_core.sop_path_generator import SopPathGenerator

    generator = SopPathGenerator(store=store)
    result = generator.generate_sops_from_doc(ctx.library_id, ctx.doc_id, store)
    sop_count = len(result.get("sops", [])) if isinstance(result, dict) else 1
    return f"SOP 生成完成，{sop_count} 个流程"


STAGE_REGISTRY: Dict[str, StageDef] = {s.key: s for s in [
    StageDef("source_prep", "源文件准备", STAGE_KIND_HARD, [], _run_source_prep),
    StageDef("convert", "格式转换", STAGE_KIND_HARD, ["source_prep"], _run_convert),
    StageDef("raw_parse", "MinerU 解析", STAGE_KIND_HARD, ["convert"], _run_raw_parse),
    StageDef("popo", "PoPo 语义增强", STAGE_KIND_SOFT, ["raw_parse"], _run_popo),
    StageDef("structure", "结构化入库", STAGE_KIND_HARD, ["raw_parse"], _run_structure),
    StageDef("fts", "全文索引", STAGE_KIND_HARD, ["structure"], _run_fts),
    StageDef("vectors", "向量索引", STAGE_KIND_SOFT, ["structure"], _run_vectors),
    StageDef("graph", "知识图谱", STAGE_KIND_SOFT, ["structure"], _run_graph),
    StageDef("sop", "SOP 生成", STAGE_KIND_SOFT, ["graph"], _run_sop),
]}

_PIPELINE_ORDER = [
    "source_prep", "convert", "raw_parse", "popo", "structure", "fts", "vectors", "graph", "sop",
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
    if any(v == "failed" for v in values):
        return "partial"
    if all(v in ("completed", "skipped") for v in values):
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
        try:
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
                message=f"{message}（{round(time.time() - t0, 1)}s）",
                started_at=started, finished_at=datetime.now().isoformat(),
            )
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
