"""评测器依赖注入：API 进程与 eval worker 进程共用（自 evals_routes._startup 拆出）。

评测执行体拆独立进程后（2026-10-20，evals_core.runner.run_worker），worker 与 API
都必须完成同样的注入（probe 检索函数、intent 分类器），否则 probe/intent 类题集
在 worker 里会按「注入缺失」语义报错。逻辑放本模块（aichat-api 层，与注入源的
docs-core/sop_api_client 同侧依赖），两边共用一份，避免双份漂移。

依赖方向不变：evals-core 仍不 import docs-core/sop-core——注入在进程入口完成，
经 evals_core.runner.probe_eval / intent_eval 的 set_* 注册表传入。"""


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
