# -*- coding: utf-8 -*-
"""对话黑板 M1 写路径端到端验证（**不调模型**）：真库切片 → distill_run → 落图 → 读路径渲染。

用途：发版/开关前的一条可复跑证据链——证明「蒸馏真的能落节点/边/水位、幂等、召回能渲染」，
而不只是单测通过。默认用**合成 owner**（不碰任何真实会话的图），读写都在本机 chat.sqlite。

用法（仓库根执行）：
    python scripts/verify_conv_graph_write_path.py                 # 默认最长的真实会话
    python scripts/verify_conv_graph_write_path.py <session_id> <owner_key>
清理（派生缓存，可随时重建）：
    python scripts/verify_conv_graph_write_path.py --clean <owner_key>
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "chat-history" / "src"))
sys.path.insert(0, str(ROOT / "services" / "angineer-core" / "src"))

from angineer_core.agent_messages import AgentMessage  # noqa: E402
from angineer_core.conv_graph import _is_injected, distill_run, recall, render  # noqa: E402
from chat_history.store.graph_store import ConvGraphStore  # noqa: E402

DB = ROOT / "data" / "platform" / "chat.sqlite"
DEFAULT_SESSION = "chat-muj4iiw7-2jwt5v"
DEFAULT_OWNER = "u:verify-20261005"
QUESTIONS = ("把第4题的计算过程再详细讲一遍", "刚才第二条提到的规范，具体说了什么？",
             "重力式码头抗滑稳定性验算应符合哪条规范要求？")


def clean(owner: str) -> None:
    conn = sqlite3.connect(DB)
    removed = 0
    for table in ("conv_graph_node", "conv_graph_edge", "conv_graph_version", "conv_graph_state"):
        removed += conn.execute(f"DELETE FROM {table} WHERE owner_key=?", (owner,)).rowcount
    conn.commit()
    conn.close()
    print("已清理行数:", removed)


def load_messages(session: str):
    """从 chat.sqlite 取整会话消息（tool 的 items 在 content JSON 里——落库 meta_json 被裁过）。"""
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT seq, role, content, meta_json FROM chat_messages WHERE session_id=? ORDER BY seq",
        (session,),
    ).fetchall()
    conn.close()
    messages = []
    for row in rows:
        role, content = row["role"], row["content"] or ""
        if role == "tool":
            try:
                meta = json.loads(row["meta_json"] or "{}")
            except Exception:
                meta = {}
            try:
                raw = json.loads(content)
            except Exception:
                raw = {}
            if isinstance(raw, dict) and raw:
                merged = dict(meta if isinstance(meta, dict) else {})
                merged.update(raw)
                meta = merged
            messages.append(AgentMessage(role="tool", content=content, name=meta.get("name"),
                                         meta=meta))
        elif role in ("user", "assistant"):
            messages.append(AgentMessage(role=role, content=content))
    return messages


def split_runs(messages):
    runs, current = [], []
    for message in messages:
        if message.role == "user" and not _is_injected(message.content):
            if current:
                runs.append(current)
            current = [message]
        elif current:
            current.append(message)
    if current:
        runs.append(current)
    return runs


def main(argv) -> int:
    if len(argv) >= 2 and argv[0] == "--clean":
        clean(argv[1])
        return 0
    session = argv[0] if len(argv) >= 1 else DEFAULT_SESSION
    owner = argv[1] if len(argv) >= 2 else DEFAULT_OWNER
    store = ConvGraphStore(str(DB))
    store.init()
    messages = load_messages(session)
    runs = split_runs(messages)
    print("会话 %s：%d 条消息 → %d 个 run（owner=%s）" % (session, len(messages), len(runs), owner))
    for index, run in enumerate(runs, start=1):
        result = distill_run(run, run_id="verify-%02d" % index, store=store, owner_key=owner,
                             session_id=session, scope_hash="verify", library_ids=["default"])
        print("run %-2d ops=%-3d 接受=%-3d 拒收=%-2d applied=%-5s notes=%s | %s"
              % (index, len(result.ops), len(result.accepted), len(result.rejected),
                 result.applied, result.notes or "-", (run[0].content or "").strip()[:30]))
    graph = store.load_graph(owner, session)
    kinds = {}
    for node in graph.nodes.values():
        kinds[node.kind] = kinds.get(node.kind, 0) + 1
    print("图规模：节点 %d %s / 边 %d / 水位 %s | stats=%s"
          % (len(graph.nodes), kinds, len(graph.edges), store.last_run(owner, session),
             store.stats(owner, session)))
    again = distill_run(runs[-1], run_id="verify-%02d" % len(runs), store=store,
                        owner_key=owner, session_id=session)
    print("幂等复跑：applied=%s note=%s" % (again.applied, again.note))
    for question in QUESTIONS:
        nodes = recall(graph, question)
        text = render(nodes)
        print("问：%s → 召回 %d 节点 / %d 字符（%.0f est）\n   %s"
              % (question, len(nodes), len(text), len(text) / 2, text.replace("\n", "\n   ")))
    print("清理：python scripts/verify_conv_graph_write_path.py --clean %s" % owner)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
