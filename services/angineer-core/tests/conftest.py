"""angineer-core 测试公共配置：端口注册表隔离。

2026-10-12：[server] 壳（``angineer_core.server``）在启动时会注册 HTTP 端口适配器
（六端口，见 ``server/http_ports.py``）；测试进程内注册表是全局单例，任一用例的
注册/清理都可能泄漏给后续用例。本 fixture 对每个用例快照 → 还原，保证用例间零串扰
（也保护「端口未注册→降级」类断言的既有用例）。
"""
import pytest

from angineer_core import ports


def _snapshot() -> dict:
    return {
        "normalize_query": ports.get_query_normalizer(),
        "knowledge_local": ports.get_knowledge_local_search(),
        "table_local": ports.get_table_local_search(),
        "entity_local": ports.get_entity_local_search(),
        "local_stats": ports.get_local_stats(),
        "engtool_registry": ports.get_engtool_registry(),
        "relevant_citations": ports.get_relevant_citations(),
        "table_blocks": ports.get_table_blocks_provider(),
        "local_rerank": ports.get_local_rerank(),
        "local_nodes_loader": ports.get_local_nodes_loader(),
    }


def _restore(snap: dict) -> None:
    # 显式 None = 清除该项（ports 注册表约定），此处用于「还原为未注册」
    ports.register_agent_search(
        normalize_query=snap["normalize_query"],
        knowledge_local=snap["knowledge_local"],
        table_local=snap["table_local"],
        entity_local=snap["entity_local"],
        local_stats=snap["local_stats"],
        engtool_registry=snap["engtool_registry"],
        relevant_citations=snap["relevant_citations"],
        table_blocks=snap["table_blocks"],
    )
    ports.register_local_rerank(snap["local_rerank"])
    ports.register_local_nodes_loader(snap["local_nodes_loader"])


@pytest.fixture(autouse=True)
def _isolate_ports_registry():
    snap = _snapshot()
    try:
        yield
    finally:
        _restore(snap)
