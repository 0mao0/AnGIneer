"""评测器依赖注入：API 进程与 eval worker 进程共用（自 evals_routes._startup 拆出）。

评测执行体拆独立进程后（2026-10-20，evals_core.runner.run_worker），worker 与 API
都必须完成同样的注入（probe 检索函数、intent 分类器），否则 probe/intent 类题集
在 worker 里会按「注入缺失」语义报错。逻辑放本模块（aichat-api 层，与注入源的
docs-core/sop_api_client 同侧依赖），两边共用一份，避免双份漂移。

依赖方向不变：evals-core 仍不 import docs-core/sop-core——注入在进程入口完成，
经 evals_core.runner.probe_eval / intent_eval 的 set_* 注册表传入。"""


def register_engine_ports() -> None:
    """把 docs-core 实现注入引擎端口（API 进程与 eval worker 都必须执行）。

    2026-10-20 拆 worker 时只搬了 probe/intent 注入，漏了这份引擎端口注册：
    worker 里 knowledge_search 因 knowledge_local_search=None 直接报「端口未注册」，
    正面题 0/60（API 进程 10-18 还是 56/60）。注册放本模块，API/worker 共用一份。
    """
    import logging

    logger = logging.getLogger("evals")
    try:
        from angineer_core import ports

        def _local_nodes_loader(library_id: str, doc_ids) -> list:
            from docs_core.docs_service import get_docs_service

            kp = get_docs_service()
            return [n for n in kp.list_nodes(library_id) if getattr(n, "type", "") == "document"]

        def _local_rerank(normalized_query: str, task_type: str, candidates: list) -> list:
            from docs_core.step09_query.retrieval.reranker import rerank_candidates

            return rerank_candidates(normalized_query, task_type, candidates)

        ports.register_local_nodes_loader(_local_nodes_loader)
        ports.register_local_rerank(_local_rerank)

        from docs_core.step09_query import agent_port

        ports.register_agent_search(
            normalize_query=agent_port.normalize_query,
            knowledge_local=agent_port.knowledge_local_search,
            table_local=agent_port.table_local_search,
            entity_local=agent_port.entity_local_search,
            local_stats=agent_port.local_stats,
            engtool_registry=agent_port.engtool_registry,
            relevant_citations=agent_port.relevant_citations,
            table_blocks=agent_port.table_blocks_provider,
        )
        logger.info("引擎端口已注册：local_nodes_loader / local_rerank / agent_search 八件套（docs-core 适配器）")
    except Exception as exc:  # noqa: BLE001
        logger.warning("引擎端口注册失败（policy_query 本地回退与 phrase rerank 将降级）: %s", exc)


def configure_evaluators() -> None:
    """注入 probe 检索函数与 intent 分类器（与 API 启动逐行同源）。"""
    import logging

    # probe 评测器（clause-probe 类题集）只跑检索断言，检索函数由本进程注入
    # （evals-core 不依赖 docs-core，解耦口径见 evals_core.runner.probe_eval 模块头）
    from evals_core.runner import probe_eval

    try:
        from docs_core.step09_query.retrieve_service import retrieve_knowledge

        probe_eval.set_retriever(retrieve_knowledge)
    except Exception as exc:  # noqa: BLE001
        logging.getLogger("evals").warning("probe 检索函数注入失败（探针题将报错而非静默跳过）: %s", exc)

    # intent 评测器（intent-router 类题集）只跑分类器路由断言，分类器由本进程注入：
    # 复用生产同一条链（IntentClassifier + sop_loader 算例），不另写近似实现。
    # 与 sop_routes 同惯例：本模块自建 SopLoader 实例，不 import main（入口模块名是 __main__）。
    from evals_core.runner import intent_eval

    try:
        from angineer_core import IntentClassifier
        from sop_api_client import SopApiClient

        # 与生产同源：经 sop-api HTTP + 快照兜底（不再各自直读文件）
        _intent_sop_loader = SopApiClient()

        def _classify_for_eval(query: str):
            """生产分类链（与 main._classify_intent_blocking 逐行同源）。"""
            return IntentClassifier(_intent_sop_loader.load_all()).classify_intent(query, mode="instruct")

        intent_eval.set_intent_classifier(_classify_for_eval)
    except Exception as exc:  # noqa: BLE001
        logging.getLogger("evals").warning("intent 分类器注入失败（意图题将报错而非静默跳过）: %s", exc)
