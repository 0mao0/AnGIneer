"""solo ??? 5 ????StructuredResult ? doc_blocks_graph.jsonl + meta?"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import docs_core.paths as paths
from docs_core.step04_structure.solo_engine import StructuredResult, build_structured_from_rawfiles
from docs_core.step04_structure.shared.jsonl_io import (
    _stamp_markdown_build_id,
    new_or_reuse_build_id,
)
import docs_core.docs_file_io as _afs

logger = logging.getLogger(__name__)


# 延迟获取 AnGIneer LLM 客户端，避免循环导入
def _get_llm_client():
    try:
        from ai_inference.llm_client import llm_client
        return llm_client
    except ImportError:
        return None


__all__ = ["build_structured_index_for_doc"]



# 保存 doc_blocks_graph.jsonl + doc_blocks_graph_meta.json
def _save_doc_blocks_graph(
    library_id: str,
    doc_id: str,
    result: StructuredResult,
) -> str:
    build_id = new_or_reuse_build_id(library_id, doc_id)
    jsonl_path = paths.get_graph_jsonl_path(library_id, doc_id)
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for node in result.nodes:
            f.write(json.dumps(node, ensure_ascii=False) + "\n")

    meta_path = paths.get_graph_meta_path(library_id, doc_id)
    meta = {
        "edges": result.edges,
        "stats": result.stats,
        "generated_at": datetime.now().isoformat(),
        "build_id": build_id,
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    _stamp_markdown_build_id(paths.get_parsed_markdown_path(library_id, doc_id), build_id)

    return str(meta_path)


# Phase 7/8：PoPo 信号应用（续接/表格合并注入 + 层级信号融合；有则增强、无则跳过，
# 任何异常都不阻断 solo 管线）
def _apply_popo_signals(
    library_id: str,
    doc_id: str,
    nodes: list,
    *,
    llm_client=None,
    llm_model: Optional[str] = None,
    use_llm: bool = False,
) -> tuple[list, Dict[str, Any]]:
    from docs_core.step04_structure.popo.popo_signal_aligner import align_popo_blocks
    from docs_core.step04_structure.popo.popo_signal_injector import inject_popo_signals
    from docs_core.step04_structure.popo.popo_signal_level_fusion import (
        build_popo_level_map,
        fuse_level_signals,
    )

    try:
        enriched = _afs.file_storage.read_popo_enriched_blocks(library_id, doc_id)
    except FileNotFoundError:
        return nodes, {"injection": {"skipped_reason": "no_popo"}, "level_fusion": {"skipped_reason": "no_popo"}}
    middle_path = paths.get_mineru_raw_dir(library_id, doc_id) / "middle.json"
    if not middle_path.exists():
        return nodes, {"injection": {"skipped_reason": "no_middle"}, "level_fusion": {"skipped_reason": "no_middle"}}
    try:
        middle = json.loads(middle_path.read_text(encoding="utf-8"))
        alignment = align_popo_blocks(doc_id, middle, enriched)
        if alignment.degraded:
            logger.warning(
                "PoPo 信号对齐降级，跳过注入: doc=%s reasons=%s",
                doc_id,
                alignment.reasons[:3],
            )
            skipped = {"applied": 0, "rejected": 0, "skipped_reason": "alignment_degraded"}
            return nodes, {"injection": skipped, "level_fusion": skipped}
        nodes, inject_stats = inject_popo_signals(doc_id, nodes, enriched, alignment)
        level_map = build_popo_level_map(enriched, alignment)
        popo_level_by_uid = {
            alignment.solo_block_uid_map[source_id]: level
            for source_id, level in level_map.items()
            if source_id in alignment.solo_block_uid_map
        }
        nodes, fuse_stats = fuse_level_signals(
            nodes,
            popo_level_by_uid,
            llm_client=llm_client,
            llm_model=llm_model,
            use_llm=use_llm,
        )
        return nodes, {"injection": inject_stats, "level_fusion": fuse_stats}
    except Exception as exc:
        logger.warning("PoPo 信号注入异常，跳过: doc=%s error=%s", doc_id, exc)
        skipped = {"applied": 0, "rejected": 0, "skipped_reason": f"error:{type(exc).__name__}"}
        return nodes, {"injection": skipped, "level_fusion": skipped}


# 标题层级 LLM 复核（无论有无 PoPo 信号都执行）：
# solo 规则层级（derived_level）与 PoPo 融合结果（title_level）落 jsonl 前，
# 交给 title_level_refiner 复核——编号命中的高置信度标题跳过，其余交 LLM。
def _review_title_levels_with_llm(
    nodes: list,
    *,
    doc_id: str,
    llm_client=None,
    llm_model: Optional[str] = None,
    use_llm: bool = False,
) -> tuple[list, Dict[str, Any]]:
    from docs_core.models.types import CanonicalBlock
    from docs_core.step04_structure.shared.title_level_refiner import (
        resolve_title_level_refinement,
    )

    title_nodes = [
        node for node in nodes
        if str(node.get("block_type") or "").strip() == "title"
        and str(node.get("plain_text") or "").strip()
    ]
    stats: Dict[str, Any] = {"total_titles": len(title_nodes), "llm_status": "disabled", "updated": 0}
    if not title_nodes or not (use_llm and llm_client):
        return nodes, stats

    blocks = [
        CanonicalBlock(
            block_id=str(node.get("block_uid") or node.get("id")),
            doc_id=doc_id,
            page_idx=int(node.get("page_idx") or 0),
            block_type="title",
            text=str(node.get("plain_text") or ""),
            text_clean=str(node.get("plain_text") or ""),
            reading_order=int(node.get("block_seq") or 0),
            title_level=(
                node.get("title_level")
                if node.get("title_level") is not None
                else node.get("derived_level")
            ),
            source="mineru",
        )
        for node in title_nodes
    ]
    candidates, llm_levels, status = resolve_title_level_refinement(
        blocks,
        llm_client,
        use_llm=True,
        llm_model=llm_model,
    )
    stats["llm_status"] = status
    if not llm_levels:
        return nodes, stats

    candidate_map = {candidate["block_id"]: candidate for candidate in candidates}
    by_uid = {str(node.get("block_uid") or node.get("id")): node for node in nodes}
    for block_id, (level, confidence) in llm_levels.items():
        node = by_uid.get(block_id)
        if node is None:
            continue
        candidate = candidate_map.get(block_id)
        current_confidence = float(candidate.get("confidence") or 0.0) if candidate else 0.0
        current_level = (
            node.get("title_level")
            if node.get("title_level") is not None
            else node.get("derived_level")
        )
        if current_level is None or confidence >= current_confidence:
            node["title_level"] = level
            node["derived_level"] = level
            node["derived_by"] = "rule+llm"
            stats["updated"] += 1
    return nodes, stats


# 为文档构建结构化索引（step04：只落 jsonl + meta；SQLite 由 step05 从 jsonl 重建）
def build_structured_index_for_doc(
    library_id: str,
    doc_id: str,
    strategy: str = "doc_blocks_graph_v1",
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    opts = options or {}
    use_llm = opts.get("use_llm", True)
    llm_model = str(opts.get("llm_model") or "").strip() or None
    derive_version = opts.get("derive_version", "v1")

    parsed_dir = paths.get_parsed_dir(library_id, doc_id)
    raw_dir = paths.resolve_structure_input_dir(library_id, doc_id)
    paths.resolve_structured_input_dir(raw_dir)

    llm_client = None
    if use_llm:
        llm_client = _get_llm_client()

    doc_name = ""
    doc_info = _afs.file_storage.get_doc_manifest(library_id, doc_id)
    if doc_info.get("source_file"):
        doc_name = Path(doc_info["source_file"]).name

    result = build_structured_from_rawfiles(
        parsed_dir=parsed_dir,
        doc_id=doc_id,
        doc_name=doc_name,
        llm_client=llm_client,
        options={
            "use_llm": use_llm,
            "llm_model": llm_model,
            "derive_version": derive_version,
        },
    )

    if result.stats.get("error"):
        raise ValueError(f"构建结构失败: {result.stats.get('error')}")

    signal_stats: Dict[str, Any] = {"applied": 0, "rejected": 0, "skipped_reason": "skipped"}
    title_review_stats: Dict[str, Any] = {"total_titles": 0, "llm_status": "disabled", "updated": 0}
    if result.nodes:
        result.nodes, signal_stats = _apply_popo_signals(
            library_id,
            doc_id,
            result.nodes,
            llm_client=llm_client,
            llm_model=llm_model,
            use_llm=use_llm,
        )
        result.nodes, title_review_stats = _review_title_levels_with_llm(
            result.nodes,
            doc_id=doc_id,
            llm_client=llm_client,
            llm_model=llm_model,
            use_llm=use_llm,
        )

    graph_path = _save_doc_blocks_graph(library_id, doc_id, result)

    stats = {
        "nodes_count": len(result.nodes),
        "edges_count": len(result.edges),
        "index_rows_count": len(result.index_rows),
        "llm_status": title_review_stats["llm_status"],
        "llm_model": llm_model,
        "derive_version": derive_version,
        "popo_signal": signal_stats,
        "title_level_review": title_review_stats,
        "graph_path": graph_path,
    }

    return {
        "saved_count": len(result.nodes),
        "stats": stats,
    }
