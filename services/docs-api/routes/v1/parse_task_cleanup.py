"""删除/软删除文档节点时取消仍在运行的解析任务。"""
import logging
from typing import Any

logger = logging.getLogger(__name__)


def cancel_parse_task_for_node(node: Any, orchestrator: Any) -> None:
    """若节点仍有解析任务则请求取消；取消失败仅记录日志，不阻断删除。"""
    task_id = getattr(node, "parse_task_id", None)
    if not task_id:
        return
    try:
        orchestrator.cancel_parse_task(task_id)
    except Exception:
        logger.warning(
            "取消解析任务失败 node=%s task=%s",
            getattr(node, "id", "?"),
            task_id,
            exc_info=True,
        )
