"""ParseOrchestrator 进程级单例：docs_api 包内所有路由共享同一实例。

多实例曾导致 _parsers/_cancelled 各自独立（跨路径取消静默失效），
以及 GPU 闸门序号冲突（序号重号误报"排队期间被取消"）——宿主同款教训
（services/docs-api/orchestrator.py），包内装配必须同样单例、勿改成按请求创建。

``record_actor="static-api"``：静态键路径无 pending 占位行可改名时的 uploaded_by 兜底
（静态键上传通常先插 pending 行并带键名，正常不会走到兜底）。
"""
from docs_core.parse_pipeline import ParseOrchestrator

parse_orchestrator = ParseOrchestrator(record_actor="static-api")
