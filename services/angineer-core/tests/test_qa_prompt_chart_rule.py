"""QA prompt v20：规则 18 图表化交付（docs/plan-aichat-chart-blocks.md）。"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "services" / "angineer-core" / "src"))

from angineer_core.prompts import load  # noqa: E402


def test_latest_is_v20_and_contains_chart_rule():
    text = load("agent_configs.qa_system_prompt")
    assert "angineer-chart" in text
    assert "angineer-map" in text
    assert "18." in text
    # 图表文本禁 LaTeX：echarts 不走公式引擎，图例会照抄 $...$ 原文（std-water 实测）
    assert "禁止 LaTeX" in text


def test_v20_starts_with_v19_and_rule18_is_new():
    from angineer_core.prompts.agent_configs import QA_AGENT_SYSTEM_PROMPT_V19, QA_AGENT_SYSTEM_PROMPT_V20

    assert QA_AGENT_SYSTEM_PROMPT_V20.startswith(QA_AGENT_SYSTEM_PROMPT_V19)
    assert "18." not in QA_AGENT_SYSTEM_PROMPT_V19
