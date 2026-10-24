"""answer_eval：angineer 图表块剥离——判分只消费语义内容，JSON 块是噪声。"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "services" / "evals-core" / "src"))

from evals_core.runner.answer_eval import strip_angineer_blocks  # noqa: E402


def test_strip_closed_chart_block():
    text = "对比结论如下 [K1]。\n\n```angineer-chart\n{\"chartType\":\"bar\",\"series\":[]}\n```\n\n补充说明 [K2]。"
    assert strip_angineer_blocks(text) == "对比结论如下 [K1]。\n\n\n\n补充说明 [K2]。"


def test_strip_unclosed_chart_block_tail():
    text = "结论 [K1]。\n\n```angineer-chart\n{\"chartType\":\"bar\""
    assert strip_angineer_blocks(text) == "结论 [K1]。"


def test_keep_normal_answer_and_tables():
    text = "| 年 | 值 |\n|---|---|\n| 2023 | 120 |\n\n普通 ```json {\"a\":1}``` 保留。"
    assert strip_angineer_blocks(text) == text
