"""Dispatcher 兼容壳（P7 终态）。

旧顶层分级调度 ``dispatch()`` 已由 ``agent_policy`` + ``run_agent_loop`` 取代，
本文件仅保留 SopRunner 执行内核的兼容入口，供以下场景使用：

- agent 工具 ``SopRunnerAdapter.sop_execute``（SOP 执行）；
- evals 的 SOP 隔离执行与 trace 构建。
"""

from angineer_core.sop_runner import SopRunner


class Dispatcher(SopRunner):
    """SOP 执行引擎兼容入口（原分级调度部分已移除）。"""
