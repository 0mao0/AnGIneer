"""启动自愈：把重启遗留的 queued/processing 解析任务与记录标记为 failed，避免永久僵尸。

包内版 = 宿主 services/docs-api/startup_recovery.py 去迁移部分（迁移任务自愈属管理面，
kb_migration_routes 不进包）。行级兜底 reconcile_stale_records 只应在启动时调用——此刻
不存在合法在跑任务；若挪去运行期复用必须先补线程活性判断，否则会掐死真在跑的行。
"""
import logging
from typing import Any, Optional

from docs_core.docs_api.records import list_records, update_record_status

logger = logging.getLogger(__name__)

# 重启中断后的出路：v1 断点续跑（已完成阶段复用，不重跑 MinerU）。
INTERRUPTED_ERROR = ("服务重启导致解析中断；调用 POST /api/v1/documents/{doc_id}/resume "
                     "可断点续跑（已完成阶段复用，不重跑 MinerU）")


def reconcile_stale_parse_tasks(orchestrator: Any, docs_service: Optional[Any] = None) -> int:
    """扫描 processing/queued 任务；线程不存活的一律标记 failed 并同步 node/parse_record。"""
    from docs_core.docs_service import get_docs_service

    ks = docs_service or get_docs_service()
    count = 0
    for task in list(ks.parse_tasks):
        # processing 与 queued 都可能因进程重启遗留：queued 是卡在 GPU 闸门前被杀的线程
        if str(getattr(task, "status", "") or "").strip() not in ("processing", "queued"):
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


# parse_records 非终态中需要兜底的两态；'pending' 是上传后未触发的占位态，不是僵尸，
# 宿主 2026-10-04 对账钉死，此处沿用。
_RECORD_NONTERMINAL = ("queued", "processing")


def reconcile_stale_records(orchestrator: Any, docs_service: Optional[Any] = None) -> int:
    """行级兜底：行仍 queued/processing 但内存已无活任务 → 标 failed（服务重启中断）。

    补 reconcile_stale_parse_tasks 的盲区：那条只扫得到内存任务列表，任务行在 meta
    里悬空（历史脏数据/清理遗留）时行永远僵尸。
    """
    from docs_core.docs_service import get_docs_service

    ks = docs_service or get_docs_service()
    threads = getattr(orchestrator, "_threads", {})
    count = 0
    for rec in list_records(limit=10000):
        if str(rec.get("status") or "") not in _RECORD_NONTERMINAL:
            continue
        task_id = str(rec.get("task_id") or "")
        if not task_id:
            continue  # 空 task_id 走 update_record_status 会按空串误伤其它行，跳过留人工
        thread = threads.get(task_id)
        if thread is not None and thread.is_alive():
            continue
        doc_id = str(rec.get("doc_id") or "")
        error = INTERRUPTED_ERROR.format(doc_id=doc_id)
        try:
            update_record_status(task_id, "failed", error)
            if doc_id:
                node = ks.get_node(doc_id)
                if node is not None and str(getattr(node, "status", "")) in _RECORD_NONTERMINAL:
                    ks.update_node(
                        doc_id,
                        status="failed",
                        parse_progress=100,
                        parse_stage="failed",
                        parse_error=error,
                    )
            count += 1
            logger.warning("启动自愈(行级): 标记遗留解析记录 failed task=%s doc=%s",
                           task_id, doc_id)
        except Exception:
            logger.warning("启动自愈(行级)失败 task=%s", task_id, exc_info=True)
    return count
