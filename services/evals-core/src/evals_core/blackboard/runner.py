"""M0 干跑器：读 chat.sqlite → 三臂组装 → 分段度量 → 可归因读数。

**本跑不调 LLM**（判分跑要真实模型作答，且须业主先冻结题集，见 arms §3.5/§4）。干跑回答的是：
- 臂 2 的指针是否**真的出现在 prompt 里**（在场率）——不调模型的机械验证；
- 三臂的 prompt 构成差异（闸 A 的历史段 est、闸 B 的子图段 ≤2,000 est）；
- 臂 3 的历史 tool 原文是否**真的移出**（丢弃条数）。

口径与 arms 一致：est = 字符数 ÷ 2；DB 只读；不写任何生产数据。
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import statistics
from typing import Any, Dict, List, Optional, Sequence

from angineer_core.agent_messages import AgentMessage

from .arms import ALL_ARMS, ARM_GRAPH, ARM_LABELS, compose_all
from .cases import CASES, Case

_SUBGRAPH_CAP_EST = 2000   # BB §7.2 闸 B


def repo_root() -> str:
    """仓库根（本文件位于 services/evals-core/src/evals_core/blackboard/）。"""
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".."))


def resolve_chat_db(explicit: Optional[str] = None) -> str:
    """聊天历史库路径：显式参数 > ``CHAT_DB_PATH`` > ``<repo>/data/platform/chat.sqlite``。

    与 ``chat_history.store.DB_PATH`` 同口径（阶段二三域归位后默认值即 platform/chat.sqlite）——
    这里只读，且**不写死任何 data/ 路径**（BB §5 纪律）。
    """
    if explicit:
        return explicit
    env = (os.getenv("CHAT_DB_PATH") or "").strip()
    if env:
        return env if os.path.isabs(env) else os.path.join(repo_root(), env)
    return os.path.join(repo_root(), "data", "platform", "chat.sqlite")


def load_case_messages(conn: sqlite3.Connection, case: Case) -> List[AgentMessage]:
    """取该 case 的「历史 + 本轮提问」消息（``seq <= case.seq``，按 seq 升序）。

    tool 消息按**内存态口径**装配：``content`` 是完整 JSON（items/total），``meta`` 取 content
    解析结果并叠加落库 meta 里的 ``name``/``tool_call_id``——因为落库 ``meta_json`` 已被裁成
    ``{name, tool_call_id}``，不解析 content 就拿不到 items（BB §3.1 实测陷阱）。
    """
    rows = conn.execute(
        "SELECT seq, role, content, meta_json FROM chat_messages"
        " WHERE session_id=? AND seq<=? ORDER BY seq",
        (case.session_id, case.seq),
    ).fetchall()
    messages: List[AgentMessage] = []
    for row in rows:
        role = row["role"]
        content = row["content"] or ""
        if role == "tool":
            try:
                meta = json.loads(row["meta_json"] or "{}")
            except Exception:
                meta = {}
            if not isinstance(meta, dict):
                meta = {}
            try:
                raw = json.loads(content)
            except Exception:
                raw = {}
            if isinstance(raw, dict) and raw:
                merged = dict(meta)
                merged.update(raw)
                meta = merged
            messages.append(AgentMessage(role="tool", content=content, name=meta.get("name"),
                                         tool_call_id=meta.get("tool_call_id"), meta=meta))
        elif role in ("user", "assistant", "system"):
            messages.append(AgentMessage(role=role, content=content))
    return messages


def case_fidelity(conn: sqlite3.Connection, case: Case) -> Dict[str, Any]:
    """题面保真校验：``(session_id, seq)`` 处的 user 消息必须与题集原文逐字一致。"""
    row = conn.execute(
        "SELECT content FROM chat_messages WHERE session_id=? AND seq=? AND role='user'",
        (case.session_id, case.seq),
    ).fetchone()
    actual = (row["content"] or "").strip() if row else None
    return {
        "case_id": case.case_id,
        "found": actual is not None,
        "match": actual == case.question.strip(),
        "actual": actual,
    }


def _real_user_count(messages: Sequence[AgentMessage]) -> int:
    from angineer_core.agent_configs import _is_injected_user_prompt

    return sum(1 for m in messages
               if m.role == "user" and not _is_injected_user_prompt(m.content))


def run_dry(cases: Sequence[Case] = CASES, *, db_path: Optional[str] = None,
            budget_est: int = 16_000) -> Dict[str, Any]:
    """对全部 case 跑三臂干跑，返回结构化报告。"""
    db = resolve_chat_db(db_path)
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        per_case: List[Dict[str, Any]] = []
        fidelity_fail: List[str] = []
        for case in cases:
            check = case_fidelity(conn, case)
            if not check["match"]:
                fidelity_fail.append(case.case_id)
            messages = load_case_messages(conn, case)
            arms = compose_all(case.case_id, case.question, messages, budget_est=budget_est)
            runs = max(1, _real_user_count(messages))
            entry: Dict[str, Any] = {
                "case_id": case.case_id,
                "kind": case.kind,
                "session_id": case.session_id,
                "seq": case.seq,
                "question_match": check["match"],
                "runs": runs,
                "messages": len(messages),
            }
            for arm in ALL_ARMS:
                metrics = dict(arms[arm].metrics)
                history_est = metrics["semantic_est"] + metrics["tool_line_est"]
                metrics["history_est_per_turn"] = round(history_est / runs, 1)
                entry[arm] = metrics
            entry["subgraph_chars"] = len(arms[ARM_GRAPH].subgraph_text)
            per_case.append(entry)
        summary = _summarize(per_case)
        return {
            "db": db,
            "budget_est": budget_est,
            "cases": len(per_case),
            "fidelity_failures": fidelity_fail,
            "summary": summary,
            "per_case": per_case,
        }
    finally:
        conn.close()


def _median(values: Sequence[float]) -> float:
    return round(statistics.median(values), 1) if values else 0.0


def _summarize(per_case: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    summary: Dict[str, Any] = {"arms": {}}
    for arm in ALL_ARMS:
        rows = [entry[arm] for entry in per_case]
        summary["arms"][arm] = {
            "label": ARM_LABELS[arm],
            "total_est_median": _median([r["total_est"] for r in rows]),
            "semantic_est_median": _median([r["semantic_est"] for r in rows]),
            "tool_line_est_median": _median([r["tool_line_est"] for r in rows]),
            "subgraph_est_median": _median([r["subgraph_est"] for r in rows]),
            "history_est_per_turn_median": _median([r["history_est_per_turn"] for r in rows]),
            "cases_with_pointer": sum(1 for r in rows if r["pointer_lines"] > 0),
            "cases_with_dropped_tool": sum(1 for r in rows if r["dropped_tool_messages"] > 0),
        }
    summary["subgraph_cap_est"] = _SUBGRAPH_CAP_EST
    summary["subgraph_cap_violations"] = [
        entry["case_id"] for entry in per_case if entry["arm3"]["subgraph_est"] > _SUBGRAPH_CAP_EST
    ]
    base = summary["arms"]["arm1"]["history_est_per_turn_median"]
    pointer = summary["arms"]["arm2"]["history_est_per_turn_median"]
    graph = summary["arms"]["arm3"]["history_est_per_turn_median"]
    summary["gate_a"] = {
        "arm1_arm2_delta": round(pointer - base, 1),
        "arm3_vs_arm1_delta": round(graph - base, 1),
        "note": "闸 A 是差分口径：新模式同会话历史段 est 增量必须 ≤ A-min；臂 3 不含历史 tool 段",
    }
    return summary


def to_markdown(report: Dict[str, Any]) -> str:
    """把报告渲染成可粘贴的 markdown 摘要（明细走 JSON）。"""
    lines = [
        "# 对话黑板 M0 干跑报告（不调 LLM）",
        "",
        f"- DB：`{report['db']}`（只读）",
        f"- 用例数：{report['cases']}；题面保真失败：{report['fidelity_failures'] or '无'}",
        f"- est = 字符数 ÷ 2；闸 B 子图段上限 {report['summary']['subgraph_cap_est']} est",
        "",
        "| 臂 | 总 est 中位 | 语义层 est | 历史 tool 行 est | 子图段 est | 历史段 est/轮 中位 | 指针在场 | 丢弃 tool 条数>0 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for arm in ALL_ARMS:
        s = report["summary"]["arms"][arm]
        lines.append(
            f"| {s['label']} | {s['total_est_median']} | {s['semantic_est_median']} | "
            f"{s['tool_line_est_median']} | {s['subgraph_est_median']} | "
            f"{s['history_est_per_turn_median']} | {s['cases_with_pointer']}/{report['cases']} | "
            f"{s['cases_with_dropped_tool']}/{report['cases']} |"
        )
    gate = report["summary"]["gate_a"]
    lines += [
        "",
        f"- 闸 A：臂 2 − 臂 1 = {gate['arm1_arm2_delta']} est/轮；臂 3 − 臂 1 = {gate['arm3_vs_arm1_delta']} est/轮",
        f"- 闸 B：子图段超限用例 = {report['summary']['subgraph_cap_violations'] or '无'}",
    ]
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="对话黑板 M0 干跑（只读 chat.sqlite，不调 LLM）")
    parser.add_argument("--db", default=None, help="chat.sqlite 路径（默认走 CHAT_DB_PATH / platform/chat.sqlite）")
    parser.add_argument("--budget-est", type=int, default=16_000, help="预算 est（QA 档默认 16k）")
    parser.add_argument("--json", action="store_true", help="输出完整 JSON 报告")
    parser.add_argument("--out", default=None, help="把完整 JSON 写到该文件")
    args = parser.parse_args(argv)

    report = run_dry(db_path=args.db, budget_est=args.budget_est)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else to_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
