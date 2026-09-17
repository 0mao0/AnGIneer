"""聊天历史包：store/（HistoryStore 的 sqlite 实现）+ routes/（FastAPI 路由）。

解耦纪律（docs/plan-chat-history.md §3）：
- 只依赖 angineer-core 的协议与消息模型、shared 的基础库与 sqlite；**不 import docs_core**。
- 策略参数（30 轮阈值 / 保留天数 / 是否强制登录）一律注入，不写死在端点里。
"""
