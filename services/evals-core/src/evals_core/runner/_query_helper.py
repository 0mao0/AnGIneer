"""评测器共用查询桥接模块。

封装 Dispatcher.dispatch() 的调用，注入 SOP Loader 等依赖，
供所有评测器统一使用。

评测器只依赖 angineer-core（大脑），不直接依赖 docs-core / sop-core。
所有后续调度、分析、编排，均由 angineer-core.Dispatcher 完成。
"""
import os
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_sop_loader = None


def _ensure_sop_loader():
    """懒加载 SOP Loader 单例。"""
    global _sop_loader
    if _sop_loader is not None:
        return _sop_loader

    try:
        from sop_core.sop_loader import SopLoader
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".."))
        sop_base_dir = os.path.join(root_dir, "data", "sops")
        _sop_loader = SopLoader(sop_base_dir)
        return _sop_loader
    except Exception as exc:
        logger.warning(f"SOP Loader 初始化失败: {exc}")
        return None


def run_eval_query(
    query: str,
    library_id: str = "default",
    doc_ids: Optional[List[str]] = None,
    session_id: str = "",
) -> Dict[str, Any]:
    """
    评测器专用查询入口，通过 angineer-core.Dispatcher.dispatch() 执行。

    不走 HTTP，不依赖 FastAPI，不依赖 asyncio。
    在评测器的 daemon 线程中直接调用即可。

    Args:
        query: 用户查询文本
        library_id: 知识库 ID
        doc_ids: 限定文档 ID 列表
        session_id: 会话 ID（仅用于日志追踪）

    Returns:
        与 /api/query 相同结构的字典
    """
    try:
        from angineer_core.dispatcher import Dispatcher

        sop_loader = _ensure_sop_loader()

        dispatcher = Dispatcher()
        result = dispatcher.dispatch(
            query=query,
            library_id=library_id,
            doc_ids=doc_ids or [],
            sop_loader=sop_loader,
        )

        return result

    except Exception as exc:
        logger.error(f"评测查询失败 (session={session_id}): {exc}", exc_info=True)
        return {"error": f"评测查询失败: {exc}"}
