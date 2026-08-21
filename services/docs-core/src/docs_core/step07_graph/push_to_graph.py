"""把解析产物的 blocks 推入知识图谱（实体提取 + 关系推断）。"""

import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


def _emit_on_step(
    on_step: Optional[Callable[[str, str, str], None]],
    step: str,
    status: str = "done",
    detail: str = "",
) -> None:
    if on_step is not None:
        try:
            on_step(step, status, detail)
        except Exception as exc:
            # 取消异常必须向上传播（on_step 兼作取消点），其余回调失败仅告警
            if type(exc).__name__ == "ParseTaskCancelledError":
                raise
            logger.warning("图谱步骤回调失败 step=%s", step, exc_info=True)


def _run_push(
    library_id: str,
    doc_id: str,
    graph_db_path: Optional[str] = None,
    enable_llm: bool = False,
    ignored_entity_names: Optional[List[str]] = None,
    on_step: Optional[Callable[[str, str, str], None]] = None,
) -> Dict[str, Any]:
    from docs_core.paths import resolve_graph_db_path
    from docs_core.step04_structure.shared.jsonl_io import get_doc_blocks_graph
    from docs_core.docs_file_io import file_storage
    from docs_core.step07_graph.evidence_builder import build_evidence_packets
    from docs_core.step07_graph.graph_orchestrator import GraphOrchestrator
    from docs_core.step07_graph.graph_store import GraphStore

    db_path = graph_db_path or str(resolve_graph_db_path())
    content = file_storage.read_markdown(library_id, doc_id) or ""
    graph = get_doc_blocks_graph(library_id, doc_id)
    structured_items = (
        [
            node
            for node in graph.get("nodes", [])
            if str(node.get("layout_category") or "") != "attachment"
        ]
        if graph
        else []
    )
    _emit_on_step(on_step, "解析产物加载", "done", f"{len(structured_items)} blocks")

    packets = build_evidence_packets(
        library_id=library_id,
        doc_id=doc_id,
        doc_title=doc_id,
        document_content=content,
        structured_items=structured_items,
        doc_blocks_graph=graph,
    )
    _emit_on_step(on_step, "evidence packets 构建", "done", f"{len(packets)} 个")

    store = GraphStore(db_path)
    orchestrator = GraphOrchestrator(store)
    orchestrator.load_seed_entities()
    _emit_on_step(on_step, "种子实体加载", "done", db_path)
    result = orchestrator.expand_all_packets(
        packets, enable_llm=enable_llm, ignored_entity_names=ignored_entity_names or []
    )
    _emit_on_step(
        on_step, "实体/关系扩展", "done",
        f"{result.get('total_entities_found', 0)} 实体 / {result.get('total_relations_added', 0)} 关系",
    )
    return {"pushed": True, **result}


def push_to_graph(
    library_id: str,
    doc_id: str,
    graph_db_path: Optional[str] = None,
    enable_llm: bool = False,
    ignored_entity_names: Optional[List[str]] = None,
    on_step: Optional[Callable[[str, str, str], None]] = None,
) -> Dict[str, Any]:
    """Push a parsed document's blocks to the knowledge graph for entity extraction."""
    try:
        result = _run_push(
            library_id=library_id,
            doc_id=doc_id,
            graph_db_path=graph_db_path,
            enable_llm=enable_llm,
            ignored_entity_names=ignored_entity_names,
            on_step=on_step,
        )
    except ImportError as e:
        logger.warning("knowledge-graph module not available: %s", e)
        return {"pushed": False, "error": str(e)}
    except Exception as e:
        # 取消异常必须向上传播，其余异常按失败返回
        if type(e).__name__ == "ParseTaskCancelledError":
            raise
        logger.exception("push_to_graph failed for %s/%s: %s", library_id, doc_id, e)
        return {"pushed": False, "error": str(e)}

    result["entities_count"] = result.get("total_entities_found", 0)
    result["relations_count"] = result.get("total_relations_added", 0)
    return result


__all__ = ["push_to_graph"]
