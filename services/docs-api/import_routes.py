"""语料包 v2 导入路由（P3-1）：上传 → 预检 → 应用 → 进度/清理。

鉴权：全部 ``Depends(resolve_admin_session)``。上传落 data/scratch/imports/<task>/package.zip，
预检走 ``apply_import(apply=False)``（不写数据）；应用在后台线程跑，进程内任务表，单飞。
应用阶段不可取消（包已开始落位，半截状态靠冲突闸兜底）；上传/预检阶段可 DELETE 清暂存。
"""
from __future__ import annotations

import os
import shutil
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from admin_auth import resolve_admin_session
from docs_core import library_registry
from docs_core.corpus_package import BundleError, apply_import
from docs_core.library_registry import resolve_data_root

import_router = APIRouter()

IMPORT_MAX_BYTES = int(os.getenv("IMPORT_MAX_BYTES", str(20 * 1024 ** 3)))
_UPLOAD_CHUNK = 1 << 20


@dataclass
class ImportTask:
    task_id: str
    package_path: Path
    group_name: str
    group_display_name: str
    with_vectors: bool
    status: str = "previewed"       # previewed|running|completed|failed
    stage: str = "previewed"
    message: str = ""
    error: str = ""
    preview: Dict[str, Any] = field(default_factory=dict)
    applied_libraries: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "stage": self.stage,
            "message": self.message,
            "error": self.error,
            "group_name": self.group_name,
            "group_display_name": self.group_display_name,
            "with_vectors": self.with_vectors,
            "preview": self.preview,
            "applied_libraries": self.applied_libraries,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


_tasks: Dict[str, ImportTask] = {}
_lock = threading.Lock()
_active_apply: Optional[str] = None


def get_tasks() -> Dict[str, ImportTask]:
    with _lock:
        return dict(_tasks)


def _task_or_404(task_id: str) -> ImportTask:
    with _lock:
        task = _tasks.get(task_id)
    if not task:
        raise HTTPException(
            status_code=404,
            detail=(
                f"导入任务不存在或已失效（进程重启后任务表丢失）；"
                f"暂存包如仍在 <data 根>/scratch/imports/{task_id}/，可用 "
                f"scripts/kb_corpus_import_cleanup.py --scratch --apply 清理"
            ),
        )
    return task


def _scratch_root() -> Path:
    return resolve_data_root() / "scratch" / "imports"


def _validate_group(group_name: str) -> None:
    if group_name in library_registry.GROUP_DEFAULTS:
        return
    if not library_registry.GROUP_NAME_RE.match(group_name or ""):
        raise HTTPException(
            status_code=400,
            detail="非法组名：须小写字母开头，2–32 位小写字母/数字/_/-",
        )


class ApplyRequest(BaseModel):
    group_name: str = Field(min_length=1, max_length=32)
    group_display_name: str = ""
    libraries: List[str] = Field(default_factory=list)


@import_router.post("/imports/upload")
async def upload_import(
    file: UploadFile = File(...),
    group_name: str = Form(""),
    group_display_name: str = Form(""),
    with_vectors: bool = Form(True),
    session: Any = Depends(resolve_admin_session),
) -> Dict[str, Any]:
    """上传 zip → 预检（不写数据）→ 返回逐库预览。"""
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="只接受 .zip 语料包")
    if group_name:
        _validate_group(group_name)
    task_id = f"imp-{uuid.uuid4().hex[:12]}"
    dest = _scratch_root() / task_id / "package.zip"
    dest.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    try:
        with dest.open("wb") as out:
            while True:
                chunk = await file.read(_UPLOAD_CHUNK)
                if not chunk:
                    break
                total += len(chunk)
                if total > IMPORT_MAX_BYTES:
                    raise HTTPException(status_code=413, detail="语料包超过上传上限")
                out.write(chunk)
        if total == 0 or not zipfile.is_zipfile(dest):
            raise HTTPException(status_code=400, detail="上传内容不是合法 zip")
        preview = apply_import(
            str(dest),
            data_root=resolve_data_root(),
            group_name=group_name,
            group_display_name=group_display_name,
            apply=False,
            with_vectors=with_vectors,
        )
    except HTTPException:
        shutil.rmtree(dest.parent, ignore_errors=True)
        raise
    except BundleError as exc:
        shutil.rmtree(dest.parent, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        shutil.rmtree(dest.parent, ignore_errors=True)
        raise

    task = ImportTask(
        task_id=task_id,
        package_path=dest,
        group_name=group_name,
        group_display_name=group_display_name,
        with_vectors=with_vectors,
        preview=preview,
        stage="previewed",
        message="预检通过，等待应用",
    )
    with _lock:
        _tasks[task_id] = task
    return task.snapshot()


@import_router.post("/imports/{task_id}/apply")
def apply_import_task(
    task_id: str,
    req: ApplyRequest,
    session: Any = Depends(resolve_admin_session),
) -> Dict[str, Any]:
    _validate_group(req.group_name)
    task = _task_or_404(task_id)
    with _lock:
        global _active_apply
        if task.status == "running" or (_active_apply and _active_apply != task_id):
            raise HTTPException(status_code=409, detail="已有导入应用在执行")
        if task.status != "previewed":
            raise HTTPException(status_code=409, detail=f"任务状态不可应用: {task.status}")
        known = {lib["library_id"] for lib in (task.preview.get("libraries") or [])}
        selected = req.libraries or sorted(known)
        unknown = sorted(set(selected) - known)
        if unknown:
            raise HTTPException(status_code=400, detail=f"包内没有这些库: {unknown}")
        task.status = "running"
        task.stage = "applying"
        task.message = "落位 / 图谱 / 快照 / 对账"
        task.group_name = req.group_name
        task.group_display_name = req.group_display_name
        task.updated_at = time.time()
        task.preview = dict(task.preview, selected_libraries=selected)
        _active_apply = task_id
    threading.Thread(target=_run_apply, args=(task_id, selected), daemon=True).start()
    return task.snapshot()


def _run_apply(task_id: str, libraries: List[str]) -> None:
    global _active_apply
    task = _task_or_404(task_id)

    def on_stage(stage: str, message: str) -> None:
        task.stage = stage
        task.message = message
        task.updated_at = time.time()

    try:
        result = apply_import(
            str(task.package_path),
            data_root=resolve_data_root(),
            group_name=task.group_name,
            group_display_name=task.group_display_name,
            libraries=libraries,
            apply=True,
            with_vectors=task.with_vectors,
            on_stage=on_stage,
        )
        task.status = "completed"
        task.stage = "reload"
        task.message = "刷新知识库缓存"
        task.applied_libraries = list(result.get("libraries") or libraries)
        try:
            from docs_core.docs_service import get_docs_service

            get_docs_service().reload_scope_cache()
        except Exception as exc:  # noqa: BLE001
            task.error = f"已导入，但 reload_scope_cache 失败，请重启 docs-api: {exc}"
        task.stage = "done"
        task.message = "导入完成"
    except Exception as exc:  # noqa: BLE001
        task.status = "failed"
        task.stage = "failed"
        task.error = (
            f"{type(exc).__name__}: {exc}；暂存包 {task.package_path}；"
            f"可 DELETE /api/knowledge/imports/{task_id} 清暂存"
        )
        task.message = "导入失败；暂存包保留，排障后可重试或 DELETE"
    finally:
        task.updated_at = time.time()
        with _lock:
            if _active_apply == task_id:
                _active_apply = None


@import_router.get("/imports/{task_id}/status")
def import_status(task_id: str, session: Any = Depends(resolve_admin_session)) -> Dict[str, Any]:
    return _task_or_404(task_id).snapshot()


@import_router.delete("/imports/{task_id}")
def delete_import(task_id: str, session: Any = Depends(resolve_admin_session)) -> Dict[str, Any]:
    task = _task_or_404(task_id)
    if task.status == "running":
        raise HTTPException(status_code=409, detail="应用执行中，不能删除暂存包")
    with _lock:
        _tasks.pop(task_id, None)
    shutil.rmtree(task.package_path.parent, ignore_errors=True)
    return {"deleted": True, "task_id": task_id}
