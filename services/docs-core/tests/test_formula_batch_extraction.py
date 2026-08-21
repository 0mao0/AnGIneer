"""公式语义 LLM 批量提取契约测试：3 个/批、整批失败重试、拆半兜底、单项空回退。"""

import json

from docs_core.step04_structure.shared.formula_semantics import (
    llm_extract_formula_params_batch,
)


def _make_items(n: int = 3):
    return [
        {"key": f"k{i}", "formula_text": f"formula {i}", "explanation_lines": ["式中："]}
        for i in range(n)
    ]


class _FakeLLM:
    """按队列返回预设响应；队列空时返回正常批量 JSON。None 表示抛异常。"""

    def __init__(self, preloaded=None):
        self.responses = list(preloaded or [])
        self.calls = 0
        self.request_sizes: list[int] = []

    def chat(self, messages, **kwargs):
        self.calls += 1
        n = len(json.loads(messages[1]["content"])["formulas"])
        self.request_sizes.append(n)
        if self.responses:
            text = self.responses.pop(0)
            if text is None:
                raise RuntimeError("provider down")
            return text
        return json.dumps({
            "formulas": [
                {
                    "index": idx,
                    "params": [{"symbol": f"s{idx}", "description": f"描述{idx}", "confidence": 0.9}],
                }
                for idx in range(n)
            ]
        })


def test_batch_groups_by_three() -> None:
    client = _FakeLLM()
    result = llm_extract_formula_params_batch(_make_items(7), client)
    assert client.request_sizes == [3, 3, 1]
    assert client.calls == 3
    assert len(result) == 7
    assert all(status == "ok" for _params, status in result.values())
    assert all(_params[0]["extracted_by"] == "llm" for _params, _status in result.values())


def test_batch_retries_once_on_invalid_json() -> None:
    client = _FakeLLM(preloaded=["not-json"])
    result = llm_extract_formula_params_batch(_make_items(3), client)
    # 第一次坏 JSON → 重试成功（第二次返回默认正常响应）
    assert client.calls == 2
    assert client.request_sizes == [3, 3]
    assert all(status == "ok" for _params, status in result.values())


def test_batch_splits_when_retry_also_fails() -> None:
    class _SplitLLM:
        def __init__(self):
            self.calls = 0
            self.request_sizes: list[int] = []

        def chat(self, messages, **kwargs):
            self.calls += 1
            n = len(json.loads(messages[1]["content"])["formulas"])
            self.request_sizes.append(n)
            if n > 1:
                return "not-json-at-all"
            return json.dumps({
                "formulas": [{"index": 0, "params": [{"symbol": "s", "description": "d", "confidence": 0.9}]}]
            })

    client = _SplitLLM()
    result = llm_extract_formula_params_batch(_make_items(3), client)
    # 3 → 坏→重试坏→拆成 1+2 → 1 成功，2 坏→重试坏→拆成 1+1 成功
    assert client.request_sizes == [3, 3, 1, 2, 2, 1, 1]
    assert client.calls == 7
    assert len(result) == 3
    assert all(status == "ok" for _params, status in result.values())


def test_batch_per_item_empty_result() -> None:
    response = json.dumps({
        "formulas": [
            {"index": 0, "params": [{"symbol": "a", "description": "甲", "confidence": 0.9}]},
            {"index": 1, "params": []},
            {"index": 2, "params": [{"symbol": "b", "description": "乙", "confidence": 0.9}]},
        ]
    })
    client = _FakeLLM(preloaded=[response])
    result = llm_extract_formula_params_batch(_make_items(3), client)
    assert result["k0"][1] == "ok"
    assert result["k1"] == ([], "empty_result")
    assert result["k2"][1] == "ok"


def test_batch_without_client_returns_empty() -> None:
    assert llm_extract_formula_params_batch(_make_items(3), None) == {}
    assert llm_extract_formula_params_batch([], object()) == {}
