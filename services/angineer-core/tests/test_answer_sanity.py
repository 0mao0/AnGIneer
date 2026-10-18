"""answer_sanity：退化判定（回显/空答/拒答）与重试开关。"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "services" / "angineer-core" / "src"))

from angineer_core import answer_sanity as s  # noqa: E402


class _Msg:
    def __init__(self, role, content, tool_calls=None):
        self.role = role
        self.content = content
        self.tool_calls = tool_calls


def test_echo_and_short():
    q = "pull every one of our antitrust matters where we drew an HSR second request"
    assert s.is_degenerate(q, q, [])
    assert s.is_degenerate("short", q, [])


def test_refusal_without_evidence_not_retried():
    q = "list all matters"
    refusal = "没有检索到足够证据支持最终结论。当前仅能确认已有片段与问题相关，但不足以安全地给出完整答案。"
    assert not s.is_degenerate(refusal, q, [_Msg("tool", '{"error": "boom"}')])


def test_refusal_with_evidence_retried():
    q = "list all matters"
    refusal = "没有检索到足够证据支持最终结论。当前仅能确认已有片段与问题相关，但不足以安全地给出完整答案。"
    tool = _Msg("tool", '{"items": [{"doc_id": "d1", "text": "Second Request issued"}]}')
    assert s.is_degenerate(refusal, q, [tool])


def test_normal_answer_ok():
    q = "list all matters"
    answer = "Matter 1003-00001: Second Request issued on 2024-07-16, see second-request-strategy-memo.docx."
    assert not s.is_degenerate(answer, q, [])


def test_retry_flag(monkeypatch):
    monkeypatch.delenv("ANGINEER_ANSWER_RETRY", raising=False)
    assert not s.retry_enabled()  # 十题门槛未过 → 默认关闭
    monkeypatch.setenv("ANGINEER_ANSWER_RETRY", "1")
    assert s.retry_enabled()
