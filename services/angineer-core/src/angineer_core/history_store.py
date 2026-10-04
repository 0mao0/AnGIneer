"""聊天历史存储协议（P-ChatHistory，§3 解耦设计的引擎侧契约）。

引擎只认识这个 Protocol，不认识 sqlite / HTTP / 游客 cookie / 保留期——
实现由 services/chat-history/store 提供，aichat-api 负责组装注入。

契约要点（docs/plan-chat-history.md D10/D11）：
- ``seq`` 唯一权威在服务端：``append`` 分配单调递增序号并返回，SSE run_end 帧
  据此下发 ``msg_seqs``，客户端快照 PUT 只接受已下发的 seq。
- ``load`` 只在「会话池新建 session」时调用一次；scope_hash 自阶段三起降级为消息级
  来源标记，不参与加载过滤（见 docs/superpowers/specs/2026-10-04-kb-multi-library-qa-design.md D6）。
"""
import hashlib
from typing import Any, Dict, List, Protocol

from angineer_core.agent_messages import AgentMessage


def scope_hash_for(library_ids: "List[str] | str", doc_ids: List[str]) -> str:
    """scope 指纹：库集合（排序去重后 join）+ 排序 doc_ids 的 sha1 前 8 位。

    阶段三（D6）：scope_hash 降级为消息级来源标记——不参与历史加载过滤，
    也不参与会话池 key（chat_agent 池 key = owner:scene:session_id）。
    多库时按集合计算；**单库输入（str 或单元素列表）与旧算法
    逐位一致**（旧会话/旧消息行不需要数据迁移）。
    """
    if isinstance(library_ids, str):
        libs = [library_ids]
    else:
        libs = sorted({str(x).strip() for x in (library_ids or []) if str(x).strip()})
    material = "|".join([",".join(libs) or "default", *sorted(str(d) for d in (doc_ids or []))])
    return hashlib.sha1(material.encode("utf-8")).hexdigest()[:8]


class HistoryStore(Protocol):
    """聊天历史存储插件协议。实现方：chat_history.store.sqlite_store.SqliteHistoryStore。"""

    def load(self, owner: str, session_id: str, scope_hash: str) -> List[AgentMessage]:
        """读出该会话全部历史消息（按 seq 升序），无则空列表。

        scope_hash 参数自阶段三起仅作协议兼容，不参与过滤（D6 会话级加载）。
        """
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
