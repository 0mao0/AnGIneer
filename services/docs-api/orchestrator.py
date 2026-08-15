"""ParseOrchestrator 进程级单例：docs_routes 与 v1 路由共享。

多实例曾导致 _parsers/_cancelled 各自独立（跨路径取消静默失效），
以及 GPU 闸门序号冲突（序号重号误报"排队期间被取消"）。
"""
from docs_core.parse_pipeline import ParseOrchestrator
from models.parse_record import sync_record_for_task

parse_orchestrator = ParseOrchestrator(record_updater=sync_record_for_task)
