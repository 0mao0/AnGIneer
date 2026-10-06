"""知识库拆分/合并迁移端点（设计 §5.7）。

鉴权（二轮评审采纳项）：8 端点全部 Depends(resolve_admin_session)——迁移是
破坏性运维操作，不接受匿名调用。操作人经 _operator 进审计与任务行。
"""
from __future__ import annotations

import os
import secrets
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from admin_auth import resolve_admin_session
from docs_core.kb_migration_audit import read_audit
from docs_core.kb_migrator import (KbMigrationRunner, KbMigrator, MigrationBlocked,
                                   PreviewResult, PreviewStaleError)

kb_migration_router = APIRouter()


def _operator(session: Any) -> str:
    """真实操作人进审计（二轮评审 P0-6 采纳）。"""
    if isinstance(session, dict):
        return str(session.get("username") or session.get("user") or "admin")
    return str(getattr(session, "username", None) or getattr(session, "user", None) or "admin")


# 惰性单例（评审 P0-2）：import 期建 DocsService 太重，且 KbMigrator() 构造即建表——
# 首请求才构建，向量面经 docs_service.vector_store 接线；全仓只允许这一处 KbMigrator()。
_migrator: Optional[KbMigrator] = None
_runner: Optional[KbMigrationRunner] = None


def get_runner() -> KbMigrationRunner:
    global _migrator, _runner
    if _runner is None:
        from docs_core.docs_service import get_docs_service
        _migrator = KbMigrator(vector_store=get_docs_service().vector_store)
        _runner = KbMigrationRunner(migrator=_migrator)
    return _runner


def get_migrator() -> KbMigrator:
    get_runner()
    assert _migrator is not None
    return _migrator


class PreviewRequest(BaseModel):
    op: str
    source_library_id: str
    target_library_id: Optional[str] = None
    new_library_id: Optional[str] = None   # 拆分必填，由前端进向导时生成（评审 P2，服务端不再兜底生成）
    new_name: str = ""
    doc_ids: Optional[List[str]] = None


class SubmitRequest(PreviewRequest):
    preview_digest: str


def _preview_to_dict(p: PreviewResult) -> Dict[str, Any]:
    return {"op": p.op, "source_library_id": p.source_library_id,
            "target_library_id": p.target_library_id, "doc_ids": p.doc_ids,
            "new_name": p.new_name, "counts": p.counts, "eval_refs": p.eval_refs,
            "blockers": p.blockers, "digest": p.digest}


@kb_migration_router.post("/migrations/preview")
def preview_migration(req: PreviewRequest, session: Any = Depends(resolve_admin_session)) -> Dict[str, Any]:
    try:
        return _preview_to_dict(get_migrator().compute_preview(**req.model_dump()))
    except MigrationBlocked as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@kb_migration_router.post("/migrations")
def submit_migration(req: SubmitRequest, session: Any = Depends(resolve_admin_session)) -> Dict[str, Any]:
    mig = get_migrator()
    try:
        preview = mig.compute_preview(**req.model_dump(exclude={"preview_digest"}))
        if preview.digest != req.preview_digest:
            raise PreviewStaleError("预览已过期，请重新预览")
    except MigrationBlocked as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except PreviewStaleError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    task_id = f"mig-{secrets.token_hex(6)}"
    params = req.model_dump(exclude={"preview_digest"})
    params["doc_ids"] = preview.doc_ids  # P0-1：合并=源库全部文档、拆分=勾选集合，全集落任务行
    mig.store.create_task(task_id, op=req.op, params=params,
                          total=len(preview.doc_ids), preview=_preview_to_dict(preview))
    try:
        get_runner().submit(task_id, operator=_operator(session))
    except MigrationBlocked as exc:
        mig.store.update_task(task_id, status="failed", error=str(exc))
        raise HTTPException(status_code=409, detail=str(exc))
    return {"task_id": task_id, "status": "running"}


@kb_migration_router.get("/migrations")
def list_migrations(limit: int = 50, session: Any = Depends(resolve_admin_session)) -> Dict[str, Any]:
    return {"tasks": get_migrator().store.list_tasks(limit)}


@kb_migration_router.get("/migrations/audit")
def get_audit(offset: int = 0, limit: int = 100,
              session: Any = Depends(resolve_admin_session)) -> Dict[str, Any]:
    entries, total = read_audit(offset, limit)
    return {"entries": entries, "total": total}


# 注意注册顺序（评审 P1-6）：/migrations/volumes 必须在 /migrations/{task_id} 之前，
# 否则 "volumes" 被当 task_id 匹配走
_VOLUMES_CACHE: Dict[str, Any] = {"at": 0.0, "data": None}
_VOLUMES_TTL_S = 300

# 阈值可配置（业主定默认：1000 篇 / 150 万向量 / 5GB），登记 .env.example
_VOLUMES_THRESHOLDS = {
    "docs": int(os.environ.get("ANGINEER_KB_SPLIT_HINT_DOCS", "1000")),
    "vectors": int(os.environ.get("ANGINEER_KB_SPLIT_HINT_VECTORS", "1500000")),
    "disk_bytes": int(os.environ.get("ANGINEER_KB_SPLIT_HINT_DISK_GB", "5")) * 1024 ** 3,
}


@kb_migration_router.get("/migrations/volumes")
def library_volumes(session: Any = Depends(resolve_admin_session)) -> Dict[str, Any]:
    if _VOLUMES_CACHE["data"] is not None and time.time() - _VOLUMES_CACHE["at"] < _VOLUMES_TTL_S:
        return _VOLUMES_CACHE["data"]
    from docs_core import library_registry
    from docs_core.step05_sqlite_fts.store.sqlite_utils import create_connection
    mig = get_migrator()
    volumes = []
    for rec in library_registry.list_libraries():
        chunks = vectors = 0
        disk_bytes = 0
        with create_connection(Path(mig.meta_db)) as conn:
            docs = conn.execute(
                "SELECT COUNT(*) FROM nodes WHERE library_id=? AND type='document' AND COALESCE(deleted,0)=0",
                (rec.library_id,),
            ).fetchone()[0]
            updated_at = conn.execute(
                "SELECT COALESCE(MAX(updated_at), '') FROM nodes WHERE library_id=?", (rec.library_id,),
            ).fetchone()[0] or ""
        try:
            with create_connection(Path(mig.group_db_for(rec.library_id))) as conn:
                chunks = conn.execute(
                    "SELECT COUNT(*) FROM canonical_chunks c JOIN canonical_documents d "
                    "ON c.doc_id=d.doc_id WHERE d.library_id=?", (rec.library_id,),
                ).fetchone()[0]
        except Exception:  # noqa: BLE001 — 单库失败不拖垮整表
            pass
        if mig.vector_store is not None:
            try:
                from qdrant_client import models
                client = mig.vector_store._get_client()
                vectors = int(client.count(
                    collection_name=rec.collection,
                    count_filter=models.Filter(must=[models.FieldCondition(
                        key="library_id", match=models.MatchValue(value=rec.library_id))]),
                    exact=True,
                ).count)
            except Exception:  # noqa: BLE001
                pass
        try:
            root = mig.libraries_root_for(rec.library_id)
            for dirpath, _dirs, files in os.walk(root):
                disk_bytes += sum(os.path.getsize(os.path.join(dirpath, f)) for f in files)
        except Exception:  # noqa: BLE001
            pass
        volumes.append({"library_id": rec.library_id, "name": rec.name, "status": rec.status,
                        "docs": docs, "chunks": chunks, "vectors": vectors,
                        "disk_bytes": disk_bytes, "updated_at": updated_at})
    data = {"volumes": volumes, "thresholds": _VOLUMES_THRESHOLDS}
    _VOLUMES_CACHE.update({"at": time.time(), "data": data})
    return data


@kb_migration_router.get("/migrations/{task_id}")
def get_migration(task_id: str, session: Any = Depends(resolve_admin_session)) -> Dict[str, Any]:
    task = get_migrator().store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"迁移任务不存在: {task_id}")
    return task


_COMPENSABLE = ("interrupted", "failed", "cancel_failed")


@kb_migration_router.post("/migrations/{task_id}/cancel")
def cancel_migration(task_id: str, session: Any = Depends(resolve_admin_session)) -> Dict[str, Any]:
    mig = get_migrator()
    task = mig.store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"迁移任务不存在: {task_id}")
    if task["status"] in ("running",):
        get_runner().request_cancel(task_id)
        return {"status": "success", "task_id": task_id,
                "message": "已请求取消，已迁移的文档会自动撤回原库"}
    if task["status"] in _COMPENSABLE and task["migrated_doc_ids"]:
        # 评审 P1-4：中断/失败态的「全部回滚」= 起线程跑 Phase R 补偿
        mig.store.update_task(task_id, status="running", stage="rollback",
                              cancel_requested=1, error=None)
        get_runner().submit(task_id, operator=_operator(session))  # run_task 首个 doc 前检查 cancel → 直接进 _compensate
        return {"status": "success", "task_id": task_id, "message": "已启动全部回滚补偿"}
    return {"status": "success", "message": f"任务已处于「{task['status']}」状态，无需取消"}


@kb_migration_router.post("/migrations/{task_id}/resume")
def resume_migration(task_id: str, session: Any = Depends(resolve_admin_session)) -> Dict[str, Any]:
    mig = get_migrator()
    task = mig.store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"迁移任务不存在: {task_id}")
    if task["status"] not in _COMPENSABLE:
        raise HTTPException(status_code=409, detail=f"当前状态「{task['status']}」不支持续跑")
    mig.store.update_task(task_id, status="running", cancel_requested=0, error=None)
    try:
        get_runner().submit(task_id, operator=_operator(session))
    except MigrationBlocked as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"status": "success", "task_id": task_id, "message": "已从断点续跑"}


@kb_migration_router.post("/migrations/{task_id}/rollback")
def rollback_migration(task_id: str, session: Any = Depends(resolve_admin_session)) -> Dict[str, Any]:
    """回滚（评审 P0-3）：建 op=rollback 新任务，doc_ids 此刻解析落 params，审计 action=rollback。

    doc_ids 规则：拆分回滚=新库当前全部文档（含增量）；合并回滚=原任务 migrated_doc_ids。
    失败/中断态放行（P1-4）：无窗口检查，等价于补偿已迁部分。
    """
    mig = get_migrator()
    task = mig.store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"迁移任务不存在: {task_id}")
    if task["status"] in _COMPENSABLE and task["migrated_doc_ids"]:
        return cancel_migration(task_id, session=session)  # 未完成的任务回滚 = Phase R 补偿
    if task["status"] != "completed":
        raise HTTPException(status_code=409, detail="只有已完成的迁移可以回滚")
    deadline = task.get("rollback_deadline")
    if deadline and datetime.now() > datetime.fromisoformat(deadline):
        raise HTTPException(status_code=410, detail="已过 7 天回滚窗口，如需合并回去请使用普通合并")
    params = task["params"]
    op = params["op"]
    # 方向：library_id=当前持有文档的库，original_source_library_id=回滚目的地
    # 拆分：持有=新库 N、目的地=源库 S；合并：持有=目标库 B、目的地=源库 A
    new_lib = params.get("new_library_id") if op == "split" else params["target_library_id"]
    original_source = params["source_library_id"]
    from docs_core import library_registry
    if op == "split":
        # 拆分回滚 = 新库当前全部文档（migrated + 增量，业主已确认增量一并带走）
        from docs_core.step05_sqlite_fts.store.sqlite_utils import create_connection
        with create_connection(Path(mig.meta_db)) as conn:
            doc_ids = sorted(r[0] for r in conn.execute(
                "SELECT id FROM nodes WHERE library_id=? AND type='document' AND COALESCE(deleted,0)=0",
                (new_lib,),
            ))
        source_rec = library_registry.get_library(original_source)
    else:
        # 合并回滚 = 原任务行 migrated_doc_ids（目标库自有文档绝不动）
        doc_ids = list(task["migrated_doc_ids"])
        source_rec = library_registry.get_library(new_lib)
    rollback_id = f"mig-{secrets.token_hex(6)}"
    rollback_params = {
        "rollback_kind": op,
        "rollback_of": task_id,
        "original_source_library_id": original_source,
        "library_id": new_lib,
        "collection": source_rec.collection if source_rec else "",
        "doc_ids": doc_ids,
    }
    mig.store.create_task(rollback_id, op="rollback", params=rollback_params, total=len(doc_ids))
    try:
        get_runner().submit(rollback_id, operator=_operator(session))
    except MigrationBlocked as exc:
        mig.store.update_task(rollback_id, status="failed", error=str(exc))
        raise HTTPException(status_code=409, detail=str(exc))
    return {"task_id": rollback_id, "status": "running",
            "message": f"回滚已启动：{len(doc_ids)} 篇文档将撤回到原库"}
