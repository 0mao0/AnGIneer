import warnings

warnings.warn(
    "sop_core.research.orchestrator is deprecated. Use knowledge_graph.graph_orchestrator instead.",
    DeprecationWarning,
    stacklevel=2,
)


class SopResearchOrchestrator:
    """已废弃 — 请使用 knowledge_graph.graph_orchestrator.GraphOrchestrator。"""

    def __init__(self, *args, **kwargs):
        warnings.warn("SopResearchOrchestrator 已被移除，操作不会执行。", DeprecationWarning, stacklevel=2)

    def cleanup_zombie_runs(self):
        pass

    def start_run(self, *args, **kwargs):
        raise NotImplementedError("请迁移到 knowledge_graph.graph_orchestrator.GraphOrchestrator")
