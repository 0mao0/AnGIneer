"""步骤八：把解析产物的 blocks 推入知识图谱（实体提取 + 关系推断）。"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def push_to_graph(library_id: str, doc_id: str, graph_db_path: Optional[str] = None) -> Dict[str, Any]:
    """Push a parsed document's blocks to the knowledge graph for entity extraction.

    This is the producer side of the docs-core → knowledge-graph pipeline.
    """
    try:
        from docs_core.paths import resolve_graph_db_path
        from docs_core.step04_structure.shared.jsonl_store import get_doc_blocks_graph
        from docs_core.docs_file_io import file_storage
        from docs_core.step07_graph.evidence_builder import build_evidence_packets
        from docs_core.step07_graph.graph_orchestrator import GraphOrchestrator
        from docs_core.step07_graph.graph_store import GraphStore
    except ImportError as e:
        logger.warning("knowledge-graph module not available: %s", e)
        return {"pushed": False, "error": str(e)}

    db_path = graph_db_path or str(resolve_graph_db_path())

    content = file_storage.read_markdown(library_id, doc_id) or ""
    graph = get_doc_blocks_graph(library_id, doc_id)
    structured_items = graph.get("nodes", []) if graph else []

    packets = build_evidence_packets(
        library_id=library_id,
        doc_id=doc_id,
        doc_title=doc_id,
        document_content=content,
        structured_items=structured_items,
        doc_blocks_graph=graph,
    )

    store = GraphStore(db_path)
    orchestrator = GraphOrchestrator(store)
    orchestrator.load_seed_entities()
    result = orchestrator.expand_all_packets(packets)

    return {"pushed": True, **result}


__all__ = ["push_to_graph"]
