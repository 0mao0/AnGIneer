"""语料包导出（管理后台）：预览 → 流式下载 → 进度轮询 → 取消。

导出 = 把选中的库打成可跨环境导入的语料包（结构见 docs/plan-standards-kb-corpus-package.md）。
**服务端不落盘**：读文件一次（同时算 sha256）写进 zip 直接推给浏览器；中断即弃，无续传。

鉴权：全部 Depends(resolve_admin_session)——导出会读全库源文件与向量快照，不接受匿名调用。

为什么「下载」本身是任务入口（而不是先提交后下载）：流式一趟就是导出本体，
没有中间产物可复用；task_id 由前端生成并作查询参数带入，服务端按它登记进度，
前端另开轮询拿阶段文字。
"""
from __future__ import annotations

import secrets
import threading
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from admin_auth import resolve_admin_session
from docs_core.corpus_package import (DEFAULT_EXCLUDE_DIRS, ExportCancelled, ExportTasks,
                                      iter_package_zip, scan_selection)
from docs_core.library_registry import resolve_data_root

export_router = APIRouter()

# 进程内任务表（导出不需要历史；服务重启即失效，前端按「已中断」处理）
_tasks = ExportTasks()

# 一次性下载凭据：浏览器的「另存为」/ 原生下载带不上 Authorization 头，
# 用短时效（120s）、单次消费、绑定 task_id 的票据换下载权，避免把会话 token 写进 URL。
_TICKET_TTL_S = 120
_tickets: Dict[str, Dict[str, Any]] = {}
_ticket_lock = threading.Lock()


def get_tasks() -> ExportTasks:
    return _tasks


def _issue_ticket(task_id: str, libs: List[str]) -> str:
    ticket = secrets.token_urlsafe(24)
    with _ticket_lock:
        now = time.time()
        for key in [k for k, v in _tickets.items() if v["expires_at"] < now]:
            _tickets.pop(key, None)          # 顺手清过期
        _tickets[ticket] = {"task_id": task_id, "libs": libs, "expires_at": now + _TICKET_TTL_S}
    return ticket


def _consume_ticket(ticket: str, task_id: str) -> bool:
    with _ticket_lock:
        entry = _tickets.pop(ticket, None)
    if not entry or entry["expires_at"] < time.time():
        return False
    return entry["task_id"] == task_id


class TicketRequest(BaseModel):
    task_id: str = Field(min_length=8, max_length=64)
    libraries: List[str] = Field(min_length=1)


@export_router.post("/exports/ticket")
def issue_export_ticket(req: TicketRequest, session: Any = Depends(resolve_admin_session)) -> Dict[str, Any]:
    """换一张一次性下载凭据（见 _issue_ticket 注释）。"""
    try:
        scan_selection(resolve_data_root(), req.libraries, exclude_dirs=DEFAULT_EXCLUDE_DIRS)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ticket": _issue_ticket(req.task_id, req.libraries), "expires_in": _TICKET_TTL_S}


class PreviewRequest(BaseModel):
    libraries: List[str] = Field(min_length=1, description="选中的 library_id（同一组）")


class PreviewResponse(BaseModel):
    libraries: List[Dict[str, Any]]
    files_bytes: int
    file_count: int
    sqlite_bytes: int
    snapshot_estimate: int
    total_estimate: int
    warnings: List[str] = Field(default_factory=list)
    active_task_id: Optional[str] = None


@export_router.post("/exports/preview")
def preview_export(req: PreviewRequest, session: Any = Depends(resolve_admin_session)) -> Dict[str, Any]:
    """体积估算 + 同组未选警告。不建快照（那是导出时的实际工作）。"""
    data_root = resolve_data_root()
    try:
        result = scan_selection(data_root, req.libraries, exclude_dirs=DEFAULT_EXCLUDE_DIRS)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    active = get_tasks().active()
    selectable = {lib["library_id"] for lib in result.libraries}
    return {
        "libraries": [{"library_id": r["library_id"], "name": r.get("name") or r["library_id"],
                       "group_name": r["group_name"], "collection": r["collection"]} for r in result.libraries],
        "files_bytes": result.files_bytes,
        "file_count": result.file_count,
        "sqlite_bytes": result.sqlite_bytes,
        "snapshot_estimate": result.snapshot_estimate,
        "total_estimate": result.total_estimate,
        "warnings": result.warnings,
        # 同组未选中的库（含空库）：空库不在前端可选清单里，「建议全选」对它们无效
        "peers": [{"library_id": p["library_id"], "name": p["name"]} for p in result.peers],
        "selectable_library_ids": sorted(selectable),
        "active_task_id": (active or {}).get("task_id"),
    }


@export_router.get("/exports/stream")
def stream_export(
    request: Request,
    task_id: str = Query(..., min_length=8, max_length=64, description="前端生成的导出任务号"),
    libraries: str = Query(..., description="逗号分隔 library_id（同一组）"),
    ticket: str = Query("", description="一次性下载凭据（原生下载通道用；给了就不校验 Bearer）"),
) -> StreamingResponse:
    """流式下载 zip。这是导出本体：连接在，导出就在；断开即停。

    鉴权二选一：Bearer 管理员会话（fetch 通道），或一次性 ticket（浏览器原生下载通道）。
    """
    if ticket:
        if not _consume_ticket(ticket, task_id):
            raise HTTPException(status_code=403, detail="下载凭据无效或已过期，请重新发起导出")
    else:
        resolve_admin_session(request)
    libs = [s.strip() for s in libraries.split(",") if s.strip()]
    if not libs:
        raise HTTPException(status_code=400, detail="至少选一个库")
    data_root = resolve_data_root()
    tasks = get_tasks()
    try:
        scan = scan_selection(data_root, libs, exclude_dirs=DEFAULT_EXCLUDE_DIRS)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        tasks.start(task_id, group=(scan.libraries[0]["group_name"] if scan.libraries else ""),
                    libs=libs, total_estimate=scan.total_estimate)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    filename = f"{scan.libraries[0]['group_name'] if scan.libraries else 'corpus'}-{'-'.join(libs)[:40]}.zip"

    def generate():
        """流式产出 zip；**任何**退出路径都要收尾任务行。

        收紧原因（2026-10-09 实踩）：客户端断连（换页/关标签/浏览器取消下载）时 Starlette
        向生成器抛 GeneratorExit，它继承 BaseException 不走 except Exception——不收尾任务
        就永远停在 running，单飞闸把后续所有导出全挡死（表现为 HTTP 409）。
        """
        failed = ""
        completed = False
        try:
            for chunk in iter_package_zip(
                libs,
                exclude_dirs=DEFAULT_EXCLUDE_DIRS,
                data_root=data_root,
                on_stage=lambda stage, message: tasks.set_progress(task_id, stage=stage, message=message),
                on_progress=lambda done, total: tasks.set_progress(task_id, bytes_out=done, total=total),
                is_cancelled=lambda: tasks.is_cancelled(task_id),
            ):
                yield chunk
            completed = True
        except ExportCancelled:
            raise
        except Exception as exc:  # noqa: BLE001 — 落任务行，前端可见原因
            failed = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            tasks.finish(task_id, error=failed, cancelled=not completed and not failed)

    return StreamingResponse(
        generate(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            # 不给 Content-Length：流式长度不可预知，chunked 传输（浏览器按进度条收）
            "Cache-Control": "no-store",
        },
    )


@export_router.get("/exports/{task_id}/status")
def export_status(task_id: str, session: Any = Depends(resolve_admin_session)) -> Dict[str, Any]:
    task = get_tasks().get(task_id)
    if not task:
        return {"task_id": task_id, "status": "unknown", "stage": "", "message": "任务不存在或已随服务重启失效"}
    total = task.get("total_bytes") or 0
    done = task.get("bytes_out") or 0
    return {
        "task_id": task_id,
        "status": task["status"],
        "stage": task["stage"],
        "message": task["message"],
        "bytes_out": done,
        "total_bytes": total,
        "percent": (round(done * 100 / total) if total else 0),
        "error": task.get("error", ""),
    }


@export_router.post("/exports/{task_id}/cancel")
def cancel_export(task_id: str, session: Any = Depends(resolve_admin_session)) -> Dict[str, Any]:
    ok = get_tasks().request_cancel(task_id)
    if not ok:
        raise HTTPException(status_code=404, detail="任务不存在或已结束")
    return {"status": "cancelling", "message": "已请求取消，服务端将在下一个检查点停止"}
