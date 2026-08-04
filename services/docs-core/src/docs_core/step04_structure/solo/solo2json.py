"""solo ??? 5 ????StructuredResult ? doc_blocks_graph.jsonl + meta?"""
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import docs_core.paths as paths
from docs_core.step04_structure.solo.solo import StructuredResult, build_structured_from_rawfiles
from docs_core.step04_structure.shared.jsonl_store import (
    _stamp_markdown_build_id,
    new_or_reuse_build_id,
)
import docs_core.assets_file_store as _afs


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

    graph_path = _save_doc_blocks_graph(library_id, doc_id, result)

    stats = {
        "nodes_count": len(result.nodes),
        "edges_count": len(result.edges),
        "index_rows_count": len(result.index_rows),
        "llm_status": result.stats.get("llm_status", "disabled"),
        "llm_model": llm_model,
        "derive_version": derive_version,
        "graph_path": graph_path,
    }

    return {
        "saved_count": len(result.nodes),
        "stats": stats,
    }
