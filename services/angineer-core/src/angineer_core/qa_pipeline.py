"""拒答话术 re-export（原 legacy 答题管线已由 agent 路径取代）。

历史：qa_pipeline 曾是旧 Dispatcher 的答案组织、两阶段抽取、拒答校验与
聊天直答管线；P7 终态后生产侧仅保留 ``REFUSAL_ANSWER_TEXT``
（常量本体在 ``agent_messages``，此处 re-export 保持旧导入兼容）。
"""

from angineer_core.agent_messages import REFUSAL_ANSWER_TEXT

__all__ = ["REFUSAL_ANSWER_TEXT"]
