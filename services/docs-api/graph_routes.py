"""Knowledge Graph API routes."""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from docs_core.step07_graph.auto_extract import spawn_llm_graph_extraction
from docs_core.step07_graph.config import EntityStatus

logger = logging.getLogger(__name__)

graph_router = APIRouter()


def _store_for_library(library_id: str):
    """按库取图谱 store（plan-graph-per-library-split：一库一文件，迁移期回退全局）。"""
    from docs_core.step07_graph.graph_files import resolve_graph_db_for_library
    from docs_core.step07_graph.graph_store import GraphStore

    return GraphStore(str(resolve_graph_db_for_library(library_id)))


def _iter_stores():
    """聚合读：遍历各库图谱文件；迁移前全局文件仍在时一并纳入（与 resolve 回退一致）。"""
    from docs_core.step07_graph.graph_files import (
        global_graph_db_path,
        iter_library_graph_paths,
    )
    from docs_core.step07_graph.graph_store import GraphStore

    paths = [p for _, p in iter_library_graph_paths()]
    legacy = global_graph_db_path()
    if legacy.exists() and legacy not in paths:
        paths.append(legacy)
    for path in paths:
        yield GraphStore(str(path))


def _find_store_for_entity(entity_id: str):
    from docs_core.step07_graph.graph_files import find_graph_db_for_entity
    from docs_core.step07_graph.graph_store import GraphStore

    located = find_graph_db_for_entity(entity_id)
    if located is None:
        return None
    return GraphStore(str(located[1]))


def _find_store_for_relation(relation_id: str):
    from docs_core.step07_graph.graph_store import GraphStore

    for store in _iter_stores():
        if store.get_relation(relation_id) is not None:
            return store
    return None


def _doc_name_map(library_id: str) -> dict:
    try:
        from docs_core.docs_file_io import file_storage
        return {d["id"]: d.get("filename", "") for d in file_storage.list_documents(library_id)}
    except Exception:
        return {}


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


class EntityReviewRequest(BaseModel):
    reason: str = ""
    reviewer: str = "admin"


class EntityRestoreRequest(BaseModel):
    library_id: str
    name: str


class EntityCreateRequest(BaseModel):
    library_id: str
    name: str
    layer: str
    aliases: List[str] = []
    description: str = ""
    source_doc: str = ""
    source_clause: str = ""


class ExtractorsRunRequest(BaseModel):
    library_id: str
    doc_id: str


@graph_router.get("/stats")
async def get_graph_stats():
    stats: Dict[str, Any] = {
        "entity_count": 0, "relation_count": 0, "entities_by_layer": {}, "relations_by_type": {},
    }
    for store in _iter_stores():
        part = store.get_stats()
        stats["entity_count"] += part["entity_count"]
        stats["relation_count"] += part["relation_count"]
        for key in ("entities_by_layer", "relations_by_type"):
            for k, v in part[key].items():
                stats[key][k] = stats[key].get(k, 0) + v
    return stats


@graph_router.get("/entities")
async def list_entities(layer: Optional[str] = None):
    from docs_core.step07_graph.config import EntityLayer

    seen: Dict[str, Any] = {}
    for store in _iter_stores():
        entities = (
            store.list_entities_by_layer(EntityLayer(layer))
            if layer else store.list_all_entities()
        )
        for e in entities:
            if e.entity_id not in seen:
                seen[e.entity_id] = e
    return [
        {"entity_id": e.entity_id, "name": e.name, "layer": e.layer.value, "aliases": e.aliases,
         "status": e.status.value}
        for e in seen.values()
        if e.status == EntityStatus.APPROVED
    ]


@graph_router.get("/entities/all")
async def list_all_library_entities(library_id: str = "default"):
    store = _store_for_library(library_id)
    entities = store.list_library_entities(library_id)
    name_map = _doc_name_map(library_id)
    return [
        {
            "entity_id": e.entity_id,
            "name": e.name,
            "layer": e.layer.value,
            "aliases": e.aliases,
            "status": e.status.value,
            "source_clause": e.source_clause,
            "source_doc": e.source_doc,
            "source_doc_name": name_map.get(e.source_doc, ""),
            "proposed_doc_id": e.proposed_doc_id,
            "proposed_doc_name": name_map.get(e.proposed_doc_id, ""),
            "created_at": e.created_at,
        }
        for e in entities
    ]


@graph_router.post("/entities")
async def create_entity(req: EntityCreateRequest):
    from docs_core.step07_graph.config import EntityLayer
    from docs_core.step07_graph.graph_store import GraphEntity

    store = _store_for_library(req.library_id)
    try:
        layer = EntityLayer(req.layer)
    except ValueError:
        raise HTTPException(status_code=400, detail="layer 必须是 concept/condition/action")

    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="实体名不能为空")

    entity = store.upsert_entity(GraphEntity(
        name=name,
        layer=layer,
        aliases=req.aliases or [],
        description=req.description,
        source_doc=req.source_doc,
        source_clause=req.source_clause,
        library_id=req.library_id,
        status=EntityStatus.APPROVED,
        proposed_doc_id=req.source_doc,
        proposed_by="manual",
    ))
    store.approve_entity(entity.entity_id, reviewer="manual")
    return {
        "entity_id": entity.entity_id,
        "name": entity.name,
        "layer": entity.layer.value,
        "aliases": entity.aliases,
        "status": entity.status.value,
    }


@graph_router.get("/entities/search")
async def search_entities(q: str, library_id: Optional[str] = None):
    if library_id:
        stores = [_store_for_library(library_id)]
    else:
        stores = list(_iter_stores())  # 未指定库 = 跨库检索（跨文件聚合去重）
    seen: Dict[str, Dict[str, str]] = {}
    for store in stores:
        results = store.search_entities(
            q, status=EntityStatus.APPROVED,
            library_id=library_id or None,
        )
        for e in results:
            seen.setdefault(e.entity_id, {
                "entity_id": e.entity_id, "name": e.name,
                "layer": e.layer.value, "status": e.status.value,
            })
    return list(seen.values())


@graph_router.get("/entities/pending")
async def list_pending_entities(library_id: str = "default"):
    store = _store_for_library(library_id)
    entities = store.list_entities_by_status(library_id, EntityStatus.PENDING)
    name_map = _doc_name_map(library_id)
    return [
        {
            "entity_id": e.entity_id,
            "name": e.name,
            "layer": e.layer.value,
            "aliases": e.aliases,
            "source_clause": e.source_clause,
            "source_doc": e.source_doc,
            "source_doc_name": name_map.get(e.source_doc, ""),
            "proposed_doc_id": e.proposed_doc_id,
            "proposed_doc_name": name_map.get(e.proposed_doc_id, ""),
            "created_at": e.created_at,
        }
        for e in entities
    ]


@graph_router.post("/entities/{entity_id}/approve")
async def approve_entity(entity_id: str, req: EntityReviewRequest):
    store = _find_store_for_entity(entity_id)
    if store is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    store.approve_entity(entity_id, reviewer=req.reviewer)
    return {"status": "ok"}


@graph_router.post("/entities/{entity_id}/reject")
async def reject_entity(entity_id: str, req: EntityReviewRequest):
    store = _find_store_for_entity(entity_id)
    if store is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    entity = store.get_entity(entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    docs = store.get_docs_referencing_entity(entity_id)
    store.reject_entity(entity_id, reason=req.reason or "管理员拒绝", reviewer=req.reviewer)
    store.delete_relations_for_entity(entity_id)
    for library_id, doc_id in docs:
        if library_id == entity.library_id:
            spawn_llm_graph_extraction(library_id, doc_id, ignored_entity_names=[entity.name])
    return {"status": "ok", "rescheduled_docs": docs}


@graph_router.delete("/entities/{entity_id}")
async def delete_entity(entity_id: str):
    store = _find_store_for_entity(entity_id)
    if store is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    entity = store.get_entity(entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    docs = store.get_docs_referencing_entity(entity_id)
    if not store.delete_entity(entity_id):
        raise HTTPException(status_code=404, detail="Entity not found")
    for library_id, doc_id in docs:
        if library_id == entity.library_id:
            spawn_llm_graph_extraction(library_id, doc_id, ignored_entity_names=[entity.name])
    return {"status": "ok", "rescheduled_docs": docs}


@graph_router.get("/entities/deleted")
async def list_deleted_entities(library_id: str = "default"):
    store = _store_for_library(library_id)
    return store.list_deleted_entities(library_id)


@graph_router.post("/entities/deleted/restore")
async def restore_deleted_entity(req: EntityRestoreRequest):
    store = _store_for_library(req.library_id)
    restored = store.restore_deleted_entity(req.library_id, req.name)
    if not restored:
        raise HTTPException(status_code=404, detail="Deleted entity not found")
    return {"status": "ok"}


@graph_router.get("/relations/{entity_id}")
async def get_entity_relations(entity_id: str, direction: str = "both"):
    # 聚合各文件：实体自有文件 + 引用方文件的拷贝件都可能带关系（拆分前跨库关系）
    seen: Dict[str, Dict[str, Any]] = {}
    for store in _iter_stores():
        for r in store.get_relations_by_entity(entity_id, direction):
            seen.setdefault(r.relation_id, {
                "relation_id": r.relation_id,
                "source_id": r.source_id,
                "target_id": r.target_id,
                "type": r.relation_type,
                "confidence": r.confidence,
                "evidence": r.evidence_text,
                "clause": r.source_clause,
                "conflict_note": r.conflict_note,
                "library_id": r.library_id,
                "doc_id": r.doc_id,
            })
    return list(seen.values())


@graph_router.get("/frameworks")
async def list_frameworks(library_id: str, doc_id: str):
    """按文档列 framework 层实体（SOP 路径来源；plan-sop-api-l4 阶段 2）。"""
    frameworks = _store_for_library(library_id).get_frameworks_by_doc(library_id, doc_id)
    return [
        {"framework_id": fw.framework_id, "name": fw.name, "steps_json": fw.steps_json,
         "source_section": fw.source_section}
        for fw in frameworks
    ]


@graph_router.get("/sop-generation-bundle")
async def get_sop_generation_bundle(library_id: str, doc_id: str):
    """一次取全 SOP 生成所需图谱数据（消费方 sop-api 生成适配器，内存物化 GraphReader）。

    enrichments 按 entity_id 组装（与 get_*_by_entity_ids 逐实体调用语义一致）。
    """
    store = _store_for_library(library_id)
    entities = store.list_entities_by_doc(library_id, doc_id)
    enrichments = {}
    for e in entities:
        enrichments[e.entity_id] = {
            "principles": [
                {"principle_id": p.principle_id, "principle_text": p.principle_text,
                 "category": p.category, "source_clause": p.source_clause}
                for p in store.get_principles_by_entity_ids([e.entity_id])
            ],
            "warnings": [
                {"warning_id": w.warning_id, "warning_text": w.warning_text,
                 "severity": w.severity, "source_section": w.source_section}
                for w in store.get_warnings_by_entity_ids([e.entity_id])
            ],
            "examples": [
                {"example_id": ex.example_id, "title": ex.title,
                 "computation_text": ex.computation_text, "inputs_json": ex.inputs_json}
                for ex in store.get_examples_by_entity_ids([e.entity_id])
            ],
        }
    return {
        "library_id": library_id,
        "doc_id": doc_id,
        "entities": [
            {"entity_id": e.entity_id, "name": e.name, "layer": e.layer.value, "aliases": e.aliases,
             "description": e.description, "status": e.status.value}
            for e in entities
        ],
        "relations": [
            {"relation_id": r.relation_id, "source_id": r.source_id, "target_id": r.target_id,
             "library_id": r.library_id, "doc_id": r.doc_id}
            for r in store.get_relations_by_doc(library_id, doc_id)
        ],
        "frameworks": [
            {"framework_id": fw.framework_id, "name": fw.name, "steps_json": fw.steps_json,
             "source_section": fw.source_section}
            for fw in store.get_frameworks_by_doc(library_id, doc_id)
        ],
        "enrichments": enrichments,
    }


@graph_router.get("/snapshot")
async def get_full_snapshot(library_id: Optional[str] = None, doc_id: Optional[str] = None):
    from docs_core.step07_graph.graph_orchestrator import GraphOrchestrator

    if library_id:
        orchestrator = GraphOrchestrator(_store_for_library(library_id))
        return orchestrator.get_graph_snapshot(library_id=library_id, doc_id=doc_id)
    # 未指定库 = 跨库聚合：实体按 id 去重（拷贝件），关系按 relation_id 去重，stats 求和
    merged: Dict[str, Any] = {"stats": None, "entities": [], "relations": []}
    seen_entities: set = set()
    seen_relations: set = set()
    for store in _iter_stores():
        part = GraphOrchestrator(store).get_graph_snapshot(library_id=None, doc_id=None)
        for e in part.get("entities", []):
            if e.get("id") not in seen_entities:
                seen_entities.add(e.get("id"))
                merged["entities"].append(e)
        for r in part.get("relations", []):
            if r.get("relation_id") not in seen_relations:
                seen_relations.add(r.get("relation_id"))
                merged["relations"].append(r)
        part_stats = part.get("stats") or {}
        if merged["stats"] is None:
            merged["stats"] = {
                "entity_count": 0, "relation_count": 0,
                "entities_by_layer": {}, "relations_by_type": {},
            }
        merged["stats"]["entity_count"] += part_stats.get("entity_count", 0)
        merged["stats"]["relation_count"] += part_stats.get("relation_count", 0)
        for key in ("entities_by_layer", "relations_by_type"):
            for k, v in (part_stats.get(key) or {}).items():
                merged["stats"][key][k] = merged["stats"][key].get(k, 0) + v
    return merged


@graph_router.post("/build/from-doc")
async def build_graph_from_doc(req: PushDocRequest):
    from docs_core.docs_file_io import file_storage
    from docs_core.step04_structure.shared.jsonl_io import get_doc_blocks_graph
    from docs_core.step07_graph.graph_store import GraphStore
    from docs_core.step07_graph.evidence_builder import build_evidence_packets
    from docs_core.step07_graph.graph_orchestrator import GraphOrchestrator

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

    store = _store_for_library(req.library_id)
    orchestrator = GraphOrchestrator(store)
    orchestrator.load_seed_entities()
    result = orchestrator.expand_all_packets(packets, enable_llm=req.enable_llm_extraction)
    snapshot = orchestrator.get_graph_snapshot(library_id=req.library_id, doc_id=req.doc_id)
    return {**result, "snapshot": snapshot}


@graph_router.post("/validate/questions")
async def validate_with_questions(req: QuestionBatchRequest):
    seen: Dict[str, str] = {}
    for store in _iter_stores():
        for e in store.list_all_entities():
            seen.setdefault(e.entity_id, e.name)
    entity_names = list(seen.values())

    from docs_core.step07_graph.question_mapper import QuestionMapper, StructuredQuestion
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
    store = _find_store_for_relation(req.relation_id)
    if store is None:
        raise HTTPException(status_code=404, detail="Relation not found")
    relation = store.get_relation(req.relation_id)

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


@graph_router.post("/extractors/run")
async def run_extractors(req: ExtractorsRunRequest):
    from docs_core.docs_file_io import file_storage
    from docs_core.step07_graph.graph_orchestrator import GraphOrchestrator

    store = _store_for_library(req.library_id)
    content = file_storage.read_markdown(req.library_id, req.doc_id) or ""
    orchestrator = GraphOrchestrator(store)
    doc_entities = store.list_entities_by_doc(req.library_id, req.doc_id)
    entity_names = [e.name for e in doc_entities]
    result = orchestrator._run_extractors(req.doc_id, req.library_id, entity_names, content)
    return result


@graph_router.get("/entities/{entity_id}/enrichment")
async def get_entity_enrichment(entity_id: str):
    store = _find_store_for_entity(entity_id)
    if store is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Entity not found")
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
    store = _store_for_library(library_id)
    docs = store.get_docs_with_graph(library_id)
    try:
        from docs_core.docs_file_io import file_storage
        name_map = {d["id"]: d.get("filename", "") for d in file_storage.list_documents(library_id)}
        for doc in docs:
            doc["name"] = name_map.get(doc["doc_id"], "")
    except Exception:
        for doc in docs:
            doc.setdefault("name", "")
    return docs
