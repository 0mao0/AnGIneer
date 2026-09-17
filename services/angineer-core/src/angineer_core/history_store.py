"""聊天历史存储协议（P-ChatHistory，§3 解耦设计的引擎侧契约）。

引擎只认识这个 Protocol，不认识 sqlite / HTTP / 游客 cookie / 保留期——
实现由 services/chat-history/store 提供，aichat-api 负责组装注入。

契约要点（docs/plan-chat-history.md D10/D11）：
- ``seq`` 唯一权威在服务端：``append`` 分配单调递增序号并返回，SSE run_end 帧
  据此下发 ``msg_seqs``，客户端快照 PUT 只接受已下发的 seq。
- ``load`` 只在「会话池新建 session」时调用一次，且必须按 scope_hash 过滤——
  引擎内存 history 与池 key（owner:scene:session_id:scope_hash）是上下文真相源。
"""
import hashlib
from typing import Any, Dict, List, Protocol

from angineer_core.agent_messages import AgentMessage


def scope_hash_for(library_id: str, doc_ids: List[str]) -> str:
    """scope 指纹：库 + 排序 doc_ids 的 sha1 前 8 位。

    与 aichat-api 会话池 key 同算法（单真相源，池化/存储共用），
    库或文档集变化即新 hash → 新会话，不回灌旧 scope 的历史。
    """
    material = "|".join([library_id or "default", *sorted(str(d) for d in (doc_ids or []))])
    return hashlib.sha1(material.encode("utf-8")).hexdigest()[:8]


class HistoryStore(Protocol):
    """聊天历史存储插件协议。实现方：chat_history.store.sqlite_store.SqliteHistoryStore。"""

    def load(self, owner: str, session_id: str, scope_hash: str) -> List[AgentMessage]:
        """读出该 scope 下的全部历史消息（按 seq 升序），无则空列表。"""
        ...

    def append(
        self,
        owner: str,
        session_id: str,
        scope_hash: str,
        messages: List[AgentMessage],
        run_meta: Dict[str, Any],
    ) -> List[int]:
        """追加一轮 run 的消息 + 审计行；返回分配的消息 seq（与 messages 对齐）。

        run_meta 约定键：run_id / model / latency_ms / status / error。
        实现须事务化：消息、会话 updated_at、chat_runs 审计行同生共死。
        """
        ...
