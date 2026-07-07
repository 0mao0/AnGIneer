import json
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from sop_core.research import (
    ResearchProjectCreate,
    ResearchProjectRecord,
    ResearchRunRecord,
    ResearchRunStart,
    ResearchReviewAction,
    ResearchCandidateRecord,
    SopDraftRecord,
    EvalDraftRecord,
    ResearchRunSummary,
    ResearchStore,
)
from sop_core.research.orchestrator import SopResearchOrchestrator

sop_research_router = APIRouter()

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
SOP_BASE_DIR = os.environ.get("SOP_DATA_DIR", os.path.join(ROOT_DIR, "data", "sops"))


class ResearchRunStartRequest(BaseModel):
    project_id: str
    library_id: str = ""
    doc_id: str = ""


class ResearchReviewRequest(BaseModel):
    reviewer: str = "admin"
    comment: str = ""


class ResearchRunController:
    def __init__(self, sop_base_dir: str):
        self._sop_base_dir = sop_base_dir
        self._store = ResearchStore(sop_base_dir)
        self._store.init_db()
        self._orchestrator = SopResearchOrchestrator(self._store, sop_base_dir)
        self._orchestrator.cleanup_zombie_runs()

    def _get_store(self) -> ResearchStore:
        # init_db 已在 __init__ 完成一次，请求级不再重复执行 executescript
        return self._store

    def _get_orchestrator(self) -> SopResearchOrchestrator:
        return self._orchestrator

    def _load_validation_issues(self, run_id: str, draft_id: str) -> list:
        """从 validations 产物中读取指定 SOP 草稿的验证问题列表。"""
        artifact_root = self._store.get_artifact_root(run_id)
        path = os.path.join(artifact_root, "validations.json")
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            entry = data.get(draft_id, {}) if isinstance(data, dict) else {}
            return entry.get("issues", []) if isinstance(entry, dict) else []
        except Exception:
            return []

    def _load_doc_payload(self, library_id: str, doc_id: str) -> Dict[str, Any]:
        from docs_core.ingest.store.assets_file_store import file_storage, get_doc_blocks_graph
        from docs_core.knowledge_service import get_knowledge_service

        content = file_storage.read_markdown(library_id, doc_id) or ""

        graph = get_doc_blocks_graph(library_id, doc_id)
        structured_items = []
        if graph and isinstance(graph, dict):
            structured_items = graph.get("nodes", [])

        doc_title = doc_id
        try:
            ks = get_knowledge_service()
            node = ks.get_node(doc_id)
            if node and hasattr(node, "title"):
                doc_title = node.title
        except Exception:
            pass

        import logging
        if not content:
            logging.getLogger(__name__).warning(
                "Document %s/%s has no parsed markdown content. "
                "Make sure the document has been uploaded and parsed before starting a research run.",
                library_id, doc_id,
            )

        return {
            "library_id": library_id,
            "doc_id": doc_id,
            "doc_title": doc_title,
            "document_content": content,
            "structured_items": structured_items,
            "doc_blocks_graph": graph,
        }

    def create_run(self, request: ResearchRunStartRequest) -> Dict[str, Any]:
        store = self._get_store()
        project = store.get_project(request.project_id)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project {request.project_id} not found")

        library_id = request.library_id or project.library_id
        doc_id = request.doc_id or project.doc_id
        if not library_id or not doc_id:
            raise HTTPException(status_code=400, detail="library_id and doc_id are required")

        doc_payload = self._load_doc_payload(library_id, doc_id)
        start_payload = ResearchRunStart(project_id=request.project_id)
        try:
            run = self._get_orchestrator().start_run(start_payload, doc_payload)
        except ValueError as e:
            # 同项目已有活跃 run → 409 冲突
            raise HTTPException(status_code=409, detail=str(e))
        return {"status": "success", "run": run.model_dump()}

    def get_run(self, run_id: str) -> Dict[str, Any]:
        store = self._get_store()
        pair = store.get_run_with_summary(run_id)
        if not pair:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
        run, summary = pair
        return {"status": "success", "run": run.model_dump(), "summary": summary.model_dump()}

    def list_runs(self, project_id: Optional[str] = None) -> Dict[str, Any]:
        store = self._get_store()
        pairs = store.list_runs_with_summary(project_id=project_id)
        results = [
            {"run": run.model_dump(), "summary": summary.model_dump()}
            for run, summary in pairs
        ]
        return {"status": "success", "runs": results}

    def stop_run(self, run_id: str) -> Dict[str, Any]:
        stopped = self._get_orchestrator().stop_run(run_id)
        if not stopped:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found or not running")
        return {"status": "success", "run_id": run_id}

    def retry_run(self, run_id: str) -> Dict[str, Any]:
        store = self._get_store()
        existing = store.get_run(run_id)
        if not existing:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
        project = store.get_project(existing.project_id)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project {existing.project_id} not found")
        doc_payload = self._load_doc_payload(project.library_id, project.doc_id)
        start_payload = ResearchRunStart(project_id=existing.project_id)
        run = self._get_orchestrator().start_run(start_payload, doc_payload)
        return {"status": "success", "run": run.model_dump()}


controller = ResearchRunController(SOP_BASE_DIR)


@sop_research_router.get("/projects")
def list_projects():
    store = controller._get_store()
    projects = store.list_projects()
    return {"status": "success", "projects": [p.model_dump() for p in projects]}


@sop_research_router.post("/projects")
def create_project(request: ResearchProjectCreate):
    store = controller._get_store()
    project = store.create_project(request)
    return {"status": "success", "project": project.model_dump()}


@sop_research_router.get("/projects/{project_id}")
def get_project(project_id: str):
    store = controller._get_store()
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return {"status": "success", "project": project.model_dump()}


@sop_research_router.post("/runs")
def create_run(request: ResearchRunStartRequest):
    return controller.create_run(request)


@sop_research_router.get("/runs")
def list_runs(project_id: Optional[str] = None):
    return controller.list_runs(project_id=project_id)


@sop_research_router.get("/runs/{run_id}")
def get_run(run_id: str):
    return controller.get_run(run_id)


@sop_research_router.post("/runs/{run_id}/stop")
def stop_run(run_id: str):
    return controller.stop_run(run_id)


@sop_research_router.post("/runs/{run_id}/retry")
def retry_run(run_id: str):
    return controller.retry_run(run_id)


@sop_research_router.get("/runs/{run_id}/candidates")
def list_candidates(run_id: str):
    store = controller._get_store()
    candidates = store.list_candidates(run_id)
    return {"status": "success", "candidates": [c.model_dump() for c in candidates]}


@sop_research_router.get("/runs/{run_id}/drafts")
def list_drafts(run_id: str):
    store = controller._get_store()
    sop_drafts = store.list_sop_drafts(run_id)
    eval_drafts = store.list_eval_drafts(run_id)
    return {
        "status": "success",
        "sop_drafts": [d.model_dump() for d in sop_drafts],
        "eval_drafts": [d.model_dump() for d in eval_drafts],
    }


@sop_research_router.get("/drafts/{draft_id}")
def get_draft(draft_id: str):
    store = controller._get_store()
    draft = store.get_sop_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail=f"SOP draft {draft_id} not found")
    detail: Dict[str, Any] = {}
    if draft.json_path and os.path.exists(draft.json_path):
        with open(draft.json_path, "r", encoding="utf-8") as f:
            detail = json.load(f)
    # 合并验证问题，供前端"验证问题"区块展示
    validation_issues = controller._load_validation_issues(draft.run_id, draft_id)
    if validation_issues:
        detail["validation_issues"] = validation_issues
    return {"status": "success", "draft": draft.model_dump(), "detail": detail}


@sop_research_router.get("/evals/{draft_id}")
def get_eval_draft(draft_id: str):
    store = controller._get_store()
    draft = store.get_eval_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail=f"Eval draft {draft_id} not found")
    detail: Dict[str, Any] = {}
    if draft.json_path and os.path.exists(draft.json_path):
        with open(draft.json_path, "r", encoding="utf-8") as f:
            detail = json.load(f)
    return {"status": "success", "draft": draft.model_dump(), "detail": detail}


@sop_research_router.post("/drafts/{draft_id}/approve-sop")
def approve_sop_draft(draft_id: str, request: ResearchReviewRequest = None):
    store = controller._get_store()
    draft = store.get_sop_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail=f"SOP draft {draft_id} not found")
    store.update_sop_draft(draft_id, review_status="approved")
    reviewer = request.reviewer if request else "admin"
    comment = request.comment if request else ""
    store.log_review("sop_draft", draft_id, "approved", reviewer, comment)
    return {"status": "success", "draft_id": draft_id, "review_status": "approved"}


@sop_research_router.post("/drafts/{draft_id}/reject")
def reject_draft(draft_id: str, request: ResearchReviewRequest = None):
    store = controller._get_store()
    draft = store.get_sop_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail=f"SOP draft {draft_id} not found")
    store.update_sop_draft(draft_id, review_status="rejected")
    reviewer = request.reviewer if request else "admin"
    comment = request.comment if request else ""
    store.log_review("sop_draft", draft_id, "rejected", reviewer, comment)
    return {"status": "success", "draft_id": draft_id, "review_status": "rejected"}


@sop_research_router.post("/evals/{draft_id}/approve-dataset")
def approve_eval_draft(draft_id: str, request: ResearchReviewRequest = None):
    store = controller._get_store()
    draft = store.get_eval_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail=f"Eval draft {draft_id} not found")
    store.update_eval_draft(draft_id, review_status="approved")
    reviewer = request.reviewer if request else "admin"
    comment = request.comment if request else ""
    store.log_review("eval_draft", draft_id, "approved", reviewer, comment)
    return {"status": "success", "draft_id": draft_id, "review_status": "approved"}


@sop_research_router.post("/evals/{draft_id}/reject")
def reject_eval_draft(draft_id: str, request: ResearchReviewRequest = None):
    store = controller._get_store()
    draft = store.get_eval_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail=f"Eval draft {draft_id} not found")
    store.update_eval_draft(draft_id, review_status="rejected")
    reviewer = request.reviewer if request else "admin"
    comment = request.comment if request else ""
    store.log_review("eval_draft", draft_id, "rejected", reviewer, comment)
    return {"status": "success", "draft_id": draft_id, "review_status": "rejected"}
