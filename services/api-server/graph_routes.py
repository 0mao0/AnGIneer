"""Knowledge Graph API routes."""

import logging
import os
import sys
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

graph_router = APIRouter()

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
KG_SRC = os.path.join(ROOT_DIR, "services", "knowledge-graph", "src")
if KG_SRC not in sys.path:
    sys.path.insert(0, KG_SRC)


def _get_store():
    from knowledge_graph.graph_store import GraphStore
    db_path = os.environ.get(
        "KG_DB_PATH",
        os.path.join(ROOT_DIR, "data", "knowledge_graph.sqlite"),
    )
    return GraphStore(db_path)


class PushDocRequest(BaseModel):
    library_id: str
    doc_id: str
    enable_llm_extraction: bool = False


class QuestionBatchRequest(BaseModel):
    questions: List[Dict[str, Any]]


class HumanReviewRequest(BaseModel):
    relation_id: str
    confidence: float
    corrected_type: Optional[str] = None
    note: str = ""


class SopExportRequest(BaseModel):
    path: List[str]
    title: str
    clause: str = ""
    include_extractions: bool = True
    library_id: str = ""
    doc_id: str = ""


class SopGenerateFromDocRequest(BaseModel):
    library_id: str
    doc_id: str


class ExtractorsRunRequest(BaseModel):
    library_id: str
    doc_id: str


@graph_router.get("/stats")
async def get_graph_stats():
    store = _get_store()
    return store.get_stats()


@graph_router.get("/entities")
async def list_entities(layer: Optional[str] = None):
    store = _get_store()
    if layer:
        from knowledge_graph.config import EntityLayer
        entities = store.list_entities_by_layer(EntityLayer(layer))
    else:
        entities = store.list_all_entities()
    return [
        {"entity_id": e.entity_id, "name": e.name, "layer": e.layer.value, "aliases": e.aliases}
        for e in entities
    ]


@graph_router.get("/entities/search")
async def search_entities(q: str):
    store = _get_store()
    results = store.search_entities(q)
    return [
        {"entity_id": e.entity_id, "name": e.name, "layer": e.layer.value}
        for e in results
    ]


@graph_router.get("/relations/{entity_id}")
async def get_entity_relations(entity_id: str, direction: str = "both"):
    store = _get_store()
    relations = store.get_relations_by_entity(entity_id, direction)
    return [
        {
            "relation_id": r.relation_id,
            "source_id": r.source_id,
            "target_id": r.target_id,
            "type": r.relation_type,
            "confidence": r.confidence,
            "evidence": r.evidence_text,
            "clause": r.source_clause,
            "conflict_note": r.conflict_note,
        }
        for r in relations
    ]


@graph_router.get("/snapshot")
async def get_full_snapshot(library_id: Optional[str] = None, doc_id: Optional[str] = None):
    store = _get_store()
    from knowledge_graph.graph_orchestrator import GraphOrchestrator
    orchestrator = GraphOrchestrator(store)
    return orchestrator.get_graph_snapshot(library_id=library_id, doc_id=doc_id)


@graph_router.post("/build/from-doc")
async def build_graph_from_doc(req: PushDocRequest):
    from docs_core.ingest.store.assets_file_store import file_storage, get_doc_blocks_graph
    from knowledge_graph.graph_store import GraphStore
    from knowledge_graph.evidence_builder import build_evidence_packets
    from knowledge_graph.graph_orchestrator import GraphOrchestrator

    content = file_storage.read_markdown(req.library_id, req.doc_id) or ""
    graph = get_doc_blocks_graph(req.library_id, req.doc_id)
    structured_items = graph.get("nodes", []) if graph else []

    doc_title = req.doc_id
    packets = build_evidence_packets(
        library_id=req.library_id,
        doc_id=req.doc_id,
        doc_title=doc_title,
        document_content=content,
        structured_items=structured_items,
        doc_blocks_graph=graph,
    )

    store = _get_store()
    orchestrator = GraphOrchestrator(store)
    orchestrator.load_seed_entities()
    result = orchestrator.expand_all_packets(packets, enable_llm=req.enable_llm_extraction)
    snapshot = orchestrator.get_graph_snapshot(library_id=req.library_id, doc_id=req.doc_id)
    return {**result, "snapshot": snapshot}


@graph_router.post("/validate/questions")
async def validate_with_questions(req: QuestionBatchRequest):
    store = _get_store()
    all_entities = store.list_all_entities()
    entity_names = [e.name for e in all_entities]

    from knowledge_graph.question_mapper import QuestionMapper, StructuredQuestion
    mapper = QuestionMapper()

    questions = []
    for i, q in enumerate(req.questions):
        questions.append(StructuredQuestion(
            question_id=q.get("id", f"q{i}"),
            condition=q.get("condition", ""),
            question=q.get("question", ""),
            answer=q.get("answer", ""),
            clauses=q.get("clauses", []),
        ))

    clusters = mapper.cluster_questions(questions)
    results = []
    for cluster_id, cluster_qs in clusters.items():
        reps = mapper.select_representatives(cluster_qs)
        for rep in reps:
            mapping = mapper.map_to_graph(rep, entity_names)
            mapping["question_id"] = rep.question_id
            mapping["cluster_id"] = cluster_id
            results.append(mapping)

    return {
        "questions_total": len(req.questions),
        "clusters": len(clusters),
        "results": results,
    }


@graph_router.post("/review")
async def human_review(req: HumanReviewRequest):
    store = _get_store()
    relation = store.get_relation(req.relation_id)
    if relation is None:
        raise HTTPException(status_code=404, detail="Relation not found")

    if req.confidence < 0:
        store.mark_relation_conflict(req.relation_id, req.note or "人工标记矛盾")
    else:
        store.add_relation(
            source_id=relation.source_id,
            target_id=relation.target_id,
            relation_type=req.corrected_type or relation.relation_type,
            confidence=req.confidence,
            evidence_text=req.note,
        )
    return {"status": "ok"}


@graph_router.post("/sop/generate")
async def generate_sop_from_path(req: SopExportRequest):
    from knowledge_graph.sop_path_generator import SopPathGenerator
    store = _get_store()
    generator = SopPathGenerator(store=store if req.include_extractions else None)
    entities_map = {}
    for name in req.path:
        entity = store.get_entity_by_name(name)
        entities_map[name] = entity.layer if entity else "concept"
    sop = generator.generate_sop_skeleton(
        sop_id=req.title,
        title=req.title,
        path_entities=req.path,
        entities=entities_map,
        source_clause=req.clause,
        library_id=req.library_id,
        doc_id=req.doc_id,
    )
    return sop


@graph_router.post("/sop/generate-from-doc")
async def generate_sops_from_doc(req: SopGenerateFromDocRequest):
    from docs_core.ingest.store.assets_file_store import file_storage
    from knowledge_graph.sop_path_generator import SopPathGenerator
    from knowledge_graph.graph_orchestrator import GraphOrchestrator

    store = _get_store()
    generator = SopPathGenerator(store=store)
    doc_entities = store.list_entities_by_doc(req.library_id, req.doc_id)
    if not doc_entities:
        raise HTTPException(status_code=404, detail=f"No entities found for doc {req.doc_id}")

    entity_names = [e.name for e in doc_entities]
    content = file_storage.read_markdown(req.library_id, req.doc_id) or ""

    existing_frameworks = store.get_frameworks_by_doc(req.library_id, req.doc_id)
    if not existing_frameworks and content:
        logger.info("Running extractors for doc %s before SOP generation...", req.doc_id)
        try:
            orchestrator = GraphOrchestrator(store)
            orchestrator._run_extractors(req.doc_id, req.library_id, entity_names, content)
        except Exception as e:
            logger.warning("Extractor run partially failed: %s", e)

    try:
        result = generator.generate_sops_from_doc(req.library_id, req.doc_id, store)
        logger.info("generate-sops-from-doc result: %s", result)
        return result
    except Exception as e:
        logger.error("generate-sops-from-doc failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@graph_router.post("/extractors/run")
async def run_extractors(req: ExtractorsRunRequest):
    from docs_core.ingest.store.assets_file_store import file_storage
    from knowledge_graph.graph_orchestrator import GraphOrchestrator

    store = _get_store()
    content = file_storage.read_markdown(req.library_id, req.doc_id) or ""
    orchestrator = GraphOrchestrator(store)
    doc_entities = store.list_entities_by_doc(req.library_id, req.doc_id)
    entity_names = [e.name for e in doc_entities]
    result = orchestrator._run_extractors(req.doc_id, req.library_id, entity_names, content)
    return result


@graph_router.get("/entities/{entity_id}/enrichment")
async def get_entity_enrichment(entity_id: str):
    store = _get_store()
    entity = store.get_entity(entity_id)
    if not entity:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Entity not found")
    principles = store.get_principles_by_entity_ids([entity_id])
    warnings = store.get_warnings_by_entity_ids([entity_id])
    examples = store.get_examples_by_entity_ids([entity_id])
    return {
        "entity": {"id": entity.entity_id, "name": entity.name, "layer": entity.layer.value,
                    "aliases": entity.aliases, "description": entity.description},
        "principles": [{"principle_id": p.principle_id, "principle_text": p.principle_text,
                         "category": p.category, "source_clause": p.source_clause} for p in principles],
        "warnings": [{"warning_id": w.warning_id, "warning_text": w.warning_text,
                       "severity": w.severity, "source_section": w.source_section} for w in warnings],
        "examples": [{"example_id": e.example_id, "title": e.title, "computation_text": e.computation_text,
                       "inputs_json": e.inputs_json} for e in examples],
    }


@graph_router.get("/docs-with-graph")
async def get_docs_with_graph(library_id: str = "default"):
    store = _get_store()
    docs = store.get_docs_with_graph(library_id)
    try:
        from docs_core.ingest.store.assets_file_store import file_storage
        name_map = {d["id"]: d.get("filename", "") for d in file_storage.list_documents(library_id)}
        for doc in docs:
            doc["name"] = name_map.get(doc["doc_id"], "")
    except Exception:
        for doc in docs:
            doc.setdefault("name", "")
    return docs
