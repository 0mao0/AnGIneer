"""answer_eval：题面 harness 收尾指令剥离。"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "services" / "evals-core" / "src"))

from evals_core.runner.answer_eval import strip_harness_instruction  # noqa: E402


def test_strip_response_md_tail():
    text = ("I'm mapping our banking relationships.\n"
            "Output: write your complete answer to `response.md` — a single self-contained "
            "markdown file with your findings.")
    assert strip_harness_instruction(text) == "I'm mapping our banking relationships."


def test_keep_normal_question():
    text = "list all matters where we drew an HSR second request"
    assert strip_harness_instruction(text) == text
