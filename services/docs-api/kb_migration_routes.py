"""知识库拆分/合并迁移端点（设计 §5.7）。

鉴权（二轮评审采纳项）：8 端点全部 Depends(resolve_admin_session)——迁移是
破坏性运维操作，不接受匿名调用。操作人经 _operator 进审计与任务行。
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from admin_auth import resolve_admin_session
from docs_core.kb_migration_audit import read_audit
from docs_core.kb_migrator import (KbMigrationRunner, KbMigrator, MigrationBlocked,
                                   PreviewResult, PreviewStaleError, resolve_destination)

logger = logging.getLogger(__name__)

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
    # 目的地二选一（拆分）：new_library_id=拆到新库（前端进向导即生成，评审 P2，服务端不兜底）；
    # target_library_id=拆出去并入已有库。合并只认 target_library_id（整库并入）
    target_library_id: Optional[str] = None
    new_library_id: Optional[str] = None
    new_name: str = ""
    doc_ids: Optional[List[str]] = None


class SubmitRequest(PreviewRequest):
    preview_digest: str


def _preview_to_dict(p: PreviewResult) -> Dict[str, Any]:
    return {"op": p.op, "source_library_id": p.source_library_id,
            "target_library_id": p.target_library_id, "doc_ids": p.doc_ids,
            "new_name": p.new_name, "new_library_id": p.new_library_id,
            "counts": p.counts, "eval_refs": p.eval_refs,
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
    # 目的地是已有库（合并/拆入已有库）时目标库同上门禁；拆到新库无第二库
    params["gate_second"] = bool(req.target_library_id)
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
#
# 缓存与代价（2026-10-17 定版）：真算一次 = qdrant 逐库计数（有索引，~0.6s）+ chunk 计数
# （~2s）+ **磁盘遍历 ~16s**（lab-firm-* 各 5–6s，十几万小文件），冷缓存首跑实测 37s。
# 原实现只有 5 分钟内存缓存，过期后下一次页面加载整表转圈 37s（业主实拍）。
# 现行策略：
#   ① 落盘快照（与 meta 库同目录 kb_volumes_cache.json）：进程重启后首屏仍有旧值；
#   ② stale-while-revalidate：超过 TTL 先返旧值 + 后台线程重算（请求不再阻塞）；
#   ③ TTL 默认 30 分钟（ANGINEER_KB_VOLUMES_TTL_S 可调）；
#   ④ 无快照时并发去重：只算一次，其余请求等结果（onMounted+onActivated 会双发）；
#   ⑤ qdrant 不可达快速熔断：一次探活失败即跳过逐库计数并标记 vector_store_ok=false
#      （原实现每库白等 ~4s、20 库 82s，且面板把失败显示成 0）。
_VOLUMES_TTL_S = int(os.environ.get("ANGINEER_KB_VOLUMES_TTL_S", "1800") or "1800")
_VOLUMES_CACHE: Dict[str, Any] = {"at": 0.0, "data": None}
_VOLUMES_CACHE_LOCK = threading.Lock()
_VOLUMES_COMPUTE_LOCK = threading.Lock()
_VOLUMES_REFRESH_STATE = {"running": False}

# 阈值可配置（业主定默认：1000 篇 / 150 万向量 / 5GB），登记 .env.example
_VOLUMES_THRESHOLDS = {
    "docs": int(os.environ.get("ANGINEER_KB_SPLIT_HINT_DOCS", "1000")),
    "vectors": int(os.environ.get("ANGINEER_KB_SPLIT_HINT_VECTORS", "1500000")),
    "disk_bytes": int(os.environ.get("ANGINEER_KB_SPLIT_HINT_DISK_GB", "5")) * 1024 ** 3,
}


def _volumes_cache_path() -> Path:
    """快照与 meta 库同目录（data 卷内，随容器重建存活）。"""
    return Path(get_migrator().meta_db).parent / "kb_volumes_cache.json"


def _compute_volumes() -> Dict[str, Any]:
    """全量重扫（真算）。调用方负责缓存/落盘；本函数只做计算。"""
    from docs_core import library_registry
    from docs_core.step05_sqlite_fts.store.sqlite_utils import create_connection

    mig = get_migrator()
    qdrant_client = None
    vector_store_ok = True
    warnings: List[str] = []
    if mig.vector_store is not None:
        try:
            qdrant_client = mig.vector_store._get_client()
            qdrant_client.get_collections()  # 一次探活；失败即熔断，避免逐库白等
        except Exception as exc:  # noqa: BLE001 — 向量面不可用不拖垮整表
            qdrant_client = None
            vector_store_ok = False
            warnings.append(f"向量库不可访问，向量列不可用：{str(exc)[:120]}")
            logger.warning("体量扫描：向量库不可访问，跳过逐库计数: %s", exc)

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
        if qdrant_client is not None:
            try:
                from qdrant_client import models
                vectors = int(qdrant_client.count(
                    collection_name=rec.collection,
                    count_filter=models.Filter(must=[models.FieldCondition(
                        key="library_id", match=models.MatchValue(value=rec.library_id))]),
                    exact=True,
                ).count)
            except Exception as exc:  # noqa: BLE001 — 单库失败只丢该行向量数
                logger.warning("体量扫描：%s 向量计数失败: %s", rec.library_id, exc)
        try:
            root = mig.libraries_root_for(rec.library_id)
            for dirpath, _dirs, files in os.walk(root):
                disk_bytes += sum(os.path.getsize(os.path.join(dirpath, f)) for f in files)
        except Exception:  # noqa: BLE001
            pass
        volumes.append({"library_id": rec.library_id, "name": rec.name, "status": rec.status,
                        "docs": docs, "chunks": chunks, "vectors": vectors,
                        "disk_bytes": disk_bytes, "updated_at": updated_at})
    return {
        "volumes": volumes,
        "thresholds": _VOLUMES_THRESHOLDS,
        "meta": {
            "computed_at": datetime.now(timezone.utc).isoformat(),
            "vector_store_ok": vector_store_ok,
            "warnings": warnings,
        },
    }


def _load_persisted_volumes() -> "tuple[Optional[Dict[str, Any]], float]":
    """读落盘快照；缺失/损坏一律当作没有（不抛）。"""
    try:
        payload = json.loads(_volumes_cache_path().read_text(encoding="utf-8"))
        data = payload.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("volumes"), list):
            return None, 0.0
        return data, float(payload.get("at") or 0.0)
    except Exception:  # noqa: BLE001 — 快照只是加速，读不到就重算
        return None, 0.0


def _store_volumes(data: Dict[str, Any]) -> None:
    """内存 + 落盘（原子替换）；落盘失败不影响本次响应。"""
    at = time.time()
    with _VOLUMES_CACHE_LOCK:
        _VOLUMES_CACHE["data"] = data
        _VOLUMES_CACHE["at"] = at
    try:
        path = _volumes_cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"at": at, "data": data}, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("体量快照落盘失败（不影响本次响应）: %s", exc)


def _current_volumes() -> "tuple[Optional[Dict[str, Any]], float]":
    """内存优先，其次落盘快照；都没有返回 (None, 0)。"""
    with _VOLUMES_CACHE_LOCK:
        if _VOLUMES_CACHE["data"] is not None:
            return _VOLUMES_CACHE["data"], float(_VOLUMES_CACHE["at"] or 0.0)
    data, at = _load_persisted_volumes()
    if data is not None:
        with _VOLUMES_CACHE_LOCK:
            _VOLUMES_CACHE["data"] = data
            _VOLUMES_CACHE["at"] = at
    return data, at


def _kick_volumes_refresh() -> None:
    """过期后台重算（daemon 线程，同一时刻只跑一个）。"""
    with _VOLUMES_CACHE_LOCK:
        if _VOLUMES_REFRESH_STATE["running"]:
            return
        _VOLUMES_REFRESH_STATE["running"] = True

    def _run() -> None:
        try:
            data = _compute_volumes()
            _store_volumes(data)
            logger.info("体量看板后台重算完成：%d 库", len(data.get("volumes") or []))
        except Exception as exc:  # noqa: BLE001 — 后台失败保留旧快照
            logger.warning("体量看板后台重算失败（保留旧快照）: %s", exc)
        finally:
            with _VOLUMES_CACHE_LOCK:
                _VOLUMES_REFRESH_STATE["running"] = False

    threading.Thread(target=_run, daemon=True, name="kb-volumes-refresh").start()


def _volumes_payload(data: Dict[str, Any], *, stale: bool, age: float = 0.0) -> Dict[str, Any]:
    """响应组装：不修改缓存对象（meta 在浅拷贝上补 age/stale）。"""
    meta = dict(data.get("meta") or {})
    meta.update({"stale": bool(stale), "age_seconds": int(max(0.0, age)), "ttl_seconds": _VOLUMES_TTL_S})
    payload = dict(data)
    payload["meta"] = meta
    return payload


@kb_migration_router.get("/migrations/volumes")
def library_volumes(refresh: bool = False, session: Any = Depends(resolve_admin_session)) -> Dict[str, Any]:
    # refresh=1（面板「刷新」按钮）强制重算并等待（2026-10-09 业主定版：转圈要盖住体量列）。
    if refresh:
        data = _compute_volumes()
        _store_volumes(data)
        return _volumes_payload(data, stale=False)

    cached, at = _current_volumes()
    if cached is not None:
        age = max(0.0, time.time() - at)
        stale = age >= _VOLUMES_TTL_S
        if stale:
            _kick_volumes_refresh()  # 先返旧值，后台重算（请求不再阻塞）
        return _volumes_payload(cached, stale=stale, age=age)

    # 无任何快照（新机器首次）：同步算一次；并发请求只算一次，其余等结果
    with _VOLUMES_COMPUTE_LOCK:
        cached, at = _current_volumes()
        if cached is not None:
            return _volumes_payload(cached, stale=False, age=max(0.0, time.time() - at))
        data = _compute_volumes()
        _store_volumes(data)
        return _volumes_payload(data, stale=False)


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

    doc_ids 规则：拆到新库回滚=新库当前全部文档（含增量）；拆入已有库/合并回滚=原任务
    migrated_doc_ids（目标库自有文档绝不动）。失败/中断态放行（P1-4）：无窗口检查，
    等价于补偿已迁部分。
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
    # 拆到新库：持有=新库 N、目的地=源库 S；拆入已有库/合并：持有=目标库、目的地=源库
    new_lib = resolve_destination(params)
    original_source = params["source_library_id"]
    destination_is_new = bool(op == "split" and params.get("new_library_id"))
    from docs_core import library_registry
    if destination_is_new:
        # 拆到新库回滚 = 新库当前全部文档（migrated + 增量，业主已确认增量一并带走）
        from docs_core.step05_sqlite_fts.store.sqlite_utils import create_connection
        with create_connection(Path(mig.meta_db)) as conn:
            doc_ids = sorted(r[0] for r in conn.execute(
                "SELECT id FROM nodes WHERE library_id=? AND type='document' AND COALESCE(deleted,0)=0",
                (new_lib,),
            ))
        source_rec = library_registry.get_library(original_source)
    else:
        # 拆入已有库/合并回滚 = 原任务行 migrated_doc_ids（目标库自有文档绝不动）
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
        # 目的地形态 + 第二库门禁：拆入已有库回滚同样锁/放行目标库，且目标库绝不退役
        "destination_is_new": destination_is_new,
        "gate_second": op == "merge" or (op == "split" and not destination_is_new),
    }
    mig.store.create_task(rollback_id, op="rollback", params=rollback_params, total=len(doc_ids))
    try:
        get_runner().submit(rollback_id, operator=_operator(session))
    except MigrationBlocked as exc:
        mig.store.update_task(rollback_id, status="failed", error=str(exc))
        raise HTTPException(status_code=409, detail=str(exc))
    return {"task_id": rollback_id, "status": "running",
            "message": f"回滚已启动：{len(doc_ids)} 篇文档将撤回到原库"}
