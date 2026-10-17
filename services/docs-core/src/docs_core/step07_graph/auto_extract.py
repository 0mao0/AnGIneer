"""解析完成后自动跑 LLM 图谱抽取的后台线程。"""

import logging
import os
import threading
from typing import List, Optional

logger = logging.getLogger(__name__)

# 全局并发上限：每篇解析完都会 spawn 一个抽取线程，本模块原先没有闸门——批量重排时
# 数百个线程同时对同一台 LLM 发 chunk 请求。2026-10-17 实踩：一次 590 篇重排让 94 个
# 抽取并发把 DGX 的 tensorfold 服务打到 accept 队列满（129/128），端口不再响应，
# 网关全 502，graph 阶段假死 40 分钟。重试救不了已挂死的服务端，只能限流入。
_GRAPH_LLM_MAX_CONCURRENCY = max(1, int(os.environ.get("GRAPH_LLM_MAX_CONCURRENCY", "6") or 6))
_GRAPH_LLM_SEMAPHORE = threading.Semaphore(_GRAPH_LLM_MAX_CONCURRENCY)


def auto_llm_enabled() -> bool:
    """是否自动跑 LLM 抽取；默认开启，可用环境变量 GRAPH_AUTO_LLM=0 关闭。"""
    return os.environ.get("GRAPH_AUTO_LLM", "1") not in ("0", "false", "False")


def spawn_llm_graph_extraction(
    library_id: str,
    doc_id: str,
    ignored_entity_names: Optional[List[str]] = None,
) -> threading.Thread:
    """启动 daemon 线程执行 LLM 抽取，不阻塞解析主流程。"""
    from docs_core.step07_graph.push_to_graph import push_to_graph

    def _worker() -> None:
        try:
            with _GRAPH_LLM_SEMAPHORE:
                result = push_to_graph(
                    library_id, doc_id, enable_llm=True, ignored_entity_names=ignored_entity_names
                )
            if not result.get("pushed"):
                logger.warning("LLM 图谱抽取失败 %s/%s: %s", library_id, doc_id, result.get("error"))
        except Exception:
            logger.exception("LLM 图谱抽取异常 %s/%s", library_id, doc_id)

    thread = threading.Thread(target=_worker, daemon=True, name=f"kg-llm-{doc_id}")
    thread.start()
    return thread
