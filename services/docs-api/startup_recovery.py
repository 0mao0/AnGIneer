"""启动自愈：把重启遗留的 processing 解析任务标记为 failed，避免永久僵尸状态。"""
import logging
from typing import Any, Optional

from models.parse_record import update_record_status

logger = logging.getLogger(__name__)

INTERRUPTED_ERROR = "服务重启导致解析中断，可调用 /api/v1/documents/{doc_id}/resume 恢复"


def reconcile_stale_parse_tasks(orchestrator: Any, docs_service: Optional[Any] = None) -> int:
    """扫描 processing 任务；线程不存活的一律标记 failed 并同步 node/parse_record。"""
    from docs_core.docs_service import get_docs_service

    ks = docs_service or get_docs_service()
    count = 0
    for task in list(ks.parse_tasks):
        if str(getattr(task, "status", "") or "").strip() != "processing":
            continue
        task_id = str(getattr(task, "id", "") or "")
        doc_id = str(getattr(task, "doc_id", "") or "")
        if not task_id:
            continue
        thread = getattr(orchestrator, "_threads", {}).get(task_id)
        if thread is not None and thread.is_alive():
            continue
        error = INTERRUPTED_ERROR.format(doc_id=doc_id)
        try:
            ks.update_parse_task(
                task_id,
                status="failed",
                progress=100,
                stage="failed",
                stage_message=error,
                error=error,
            )
            if doc_id:
                ks.update_node(
                    doc_id,
                    status="failed",
                    parse_progress=100,
                    parse_stage="failed",
                    parse_error=error,
                )
            update_record_status(task_id, "failed", error)
        except Exception:
            logger.warning("启动自愈失败 task=%s doc=%s", task_id, doc_id, exc_info=True)
            continue
        count += 1
        logger.warning("启动自愈: 标记中断解析任务 failed task=%s doc=%s", task_id, doc_id)
    return count
