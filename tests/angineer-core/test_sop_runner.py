"""P6.1 SopRunner 下沉 + P6.2 llm_generate 元工具超时单测。"""
import os
import sys
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/ai-inference/src")))

from angineer_core.base_contracts import SOP, Step  # noqa: E402
from angineer_core.sop_runner import SopRunner  # noqa: E402


class FakeTool:
    def run(self, **kwargs):
        return {"result": 42}


class FakeToolRegistry:
    @classmethod
    def get_tool(cls, name):
        return FakeTool() if name == "calculator" else None


def make_sop():
    return SOP(
        id="sop-1",
        name_zh="测试SOP",
        steps=[
            Step(
                id="s1",
                name_zh="计算",
                tool="calculator",
                inputs={"expression": "1+1"},
                outputs={"result": "result"},
            )
        ],
    )


class SopRunnerTests(unittest.TestCase):
    def test_run_sop_updates_blackboard_and_history(self):
        runner = SopRunner(llm_client=Mock())
        with patch("angineer_core.sop_runner.ToolRegistry", FakeToolRegistry):
            blackboard = runner.run_sop(make_sop(), {"user_query": "计算"})
        self.assertEqual(blackboard["result"], 42)
        self.assertEqual(len(runner.memory.history), 1)
        self.assertEqual(runner.memory.history[0].status, "success")
        self.assertIn("s1", runner.step_durations)

    def test_step_callback_receives_step_info(self):
        runner = SopRunner(llm_client=Mock())
        received = []
        with patch("angineer_core.sop_runner.ToolRegistry", FakeToolRegistry):
            runner.run_sop(make_sop(), {}, step_callback=received.append)
        self.assertEqual(received[0]["step_id"], "s1")
        self.assertEqual(received[0]["status"], "success")

    def test_build_sop_trace_works_on_runner(self):
        runner = SopRunner(llm_client=Mock())
        with patch("angineer_core.sop_runner.ToolRegistry", FakeToolRegistry):
            runner.run_sop(make_sop(), {})
        sop = make_sop()
        trace = SopRunner._build_sop_trace(runner, sop)
        self.assertEqual(trace[0]["step_id"], "s1")
        self.assertEqual(trace[0]["status"], "success")

    def test_llm_generate_meta_tool_timeout_is_recorded(self):
        def slow_chat(*args, **kwargs):
            time.sleep(5)
            return "late"

        llm = Mock(chat=Mock(side_effect=slow_chat))
        sop = SOP(
            id="sop-2",
            name_zh="LLM生成",
            steps=[Step(id="s1", tool="llm_generate", inputs={"query": "hi"}, outputs={"answer": "answer"})],
        )
        runner = SopRunner(llm_client=llm, tool_timeout_s=0.2)
        started = time.time()
        runner.run_sop(sop, {})
        elapsed = time.time() - started
        self.assertLess(elapsed, 3)
        self.assertEqual(len(runner.memory.history), 1)
        self.assertEqual(runner.memory.history[0].status, "failed")
        self.assertIn("超时", runner.memory.history[0].error)

    def test_sop_runner_default_timeout_matches_legacy(self):
        runner = SopRunner()
        self.assertEqual(runner.tool_timeout_s, 120)


if __name__ == "__main__":
    unittest.main()
