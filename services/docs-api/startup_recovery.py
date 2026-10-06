"""启动自愈：把重启遗留的 processing 解析任务标记为 failed，避免永久僵尸状态。

2026-10-04 增加行级兜底 reconcile_stale_records：旧清扫只遍历「从 meta 载回内存的任务」，
任务行本身悬空（meta 里就没有）时，parse_records 行会永远停在排队中/进行中假象。
"""
import logging
from typing import Any, Optional

from models.parse_record import update_record_status

logger = logging.getLogger(__name__)

# 2026-09-15：管理后台「解析」按钮已改 resume 语义（复用 MinerU 产物只补缺口）。旧文案只提
# v1 resume，而管理后台上传的记录 api_key_id=NULL、任何 key 调用都 403——出路对管理员不存在。
INTERRUPTED_ERROR = ("服务重启导致解析中断；在管理后台点「解析」即可断点续跑（已完成阶段复用，"
                     "不重跑 MinerU），v1 上传也可调用 /api/v1/documents/{doc_id}/resume")


def reconcile_stale_parse_tasks(orchestrator: Any, docs_service: Optional[Any] = None) -> int:
    """扫描 processing 任务；线程不存活的一律标记 failed 并同步 node/parse_record。"""
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
# 2026-10-04 对账钉死（取消接口的占位行分支已负责其幂等语义），此处不改写。
_RECORD_NONTERMINAL = ("queued", "processing")


def reconcile_stale_records(orchestrator: Any, docs_service: Optional[Any] = None) -> int:
    """行级兜底：行仍 queued/processing 但内存已无活任务 → 标 failed（服务重启中断）。

    补 reconcile_stale_parse_tasks 的盲区：那条只扫得到内存任务列表，任务行在 meta
    里悬空（历史脏数据/清理遗留）时行永远僵尸。只应在启动时调用——此刻不存在合法
    在跑任务；若日后挪去运行期复用，必须先补线程活性判断，否则会掐死真在跑的行。
    """
    from docs_core.docs_service import get_docs_service
    from models.parse_record import list_records

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
            logger.warning("启动自愈(行级): 标记遗留解析记录 failed task=%s doc=%s", task_id, doc_id)
        except Exception:
            logger.warning("启动自愈(行级)失败 task=%s", task_id, exc_info=True)
    return count


def reconcile_stale_migration_tasks(runner) -> int:
    """迁移任务启动自愈（设计 §5.4）：running/cancelling 且线程不活 → interrupted；
    switch_reload_failed → completed（N4：重启即内存快照已新，给该态一个出口，不留死态）。"""
    store = runner.migrator.store
    count = 0
    for task in store.list_tasks(limit=200):
        if task["status"] == "switch_reload_failed":
            store.update_task(task["id"], status="completed",
                              stage_message="服务重启后内存快照已刷新，切换视为完成")
            count += 1
            continue
        if task["status"] not in ("running", "cancelling"):
            continue
        thread = getattr(runner, "_threads", {}).get(task["id"])
        if thread is not None and thread.is_alive():
            continue
        store.update_task(task["id"], status="interrupted",
                          stage_message="服务重启导致迁移中断，可选择「继续完成」或「全部回滚」")
        count += 1
    return count
