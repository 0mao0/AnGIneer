"""P4.2 SopRunnerAdapter.sop_execute 单元测试。"""
import os
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/ai-inference/src")))

from angineer_core.agent_tools import SopRunnerAdapter  # noqa: E402
from angineer_core.base_contracts import RouteResult, SOP, Step  # noqa: E402
from angineer_core.memory import Memory, StepRecord  # noqa: E402


def make_sop(sop_id="sop-berth-depth", status="published"):
    return SOP(
        id=sop_id,
        name_zh="码头前沿水深计算",
        description_zh="计算码头前沿设计水深",
        status=status,
        blackboard={"required": ["T", "Z0"], "outputs": ["depth"]},
        steps=[
            Step(
                id="s1",
                name_zh="计算前沿水深",
                tool="calculator",
                inputs={"expression": "T+Z0"},
                outputs={"depth": "D"},
            )
        ],
    )


class FakeClassifier:
    """返回预置 RouteResult 的假分类器。"""

    def __init__(self, route_result):
        self.route_result = route_result
        self.last_query = None
        self.last_config_name = None

    def route(self, user_query, config_name=None, mode="instruct"):
        self.last_query = user_query
        self.last_config_name = config_name
        return self.route_result


class FakeRunner:
    """记录 run_sop 调用并产出真实 history 的假执行器。"""

    def __init__(self):
        self.memory = Memory()
        self.step_durations = {}
        self.run_sop_calls = []

    def run_sop(self, sop, initial_context, pre_logs=None, step_callback=None):
        self.run_sop_calls.append((sop, initial_context))
        self.memory.update_context({"depth": 15.2})
        self.memory.add_history(
            StepRecord(
                step_id="s1",
                tool_name="calculator",
                inputs={"expression": "T+Z0"},
                outputs={"depth": 15.2},
                status="success",
            )
        )
        return {"depth": 15.2}


class SopExecuteTests(unittest.TestCase):
    def test_routes_and_runs_sop_returns_summary_and_trace(self):
        sop = make_sop()
        route_result = RouteResult(
            sop=sop,
            args={"T": 12.8, "Z0": 0.5},
            reason="命中码头水深 SOP",
            confidence=0.87,
            candidates=[],
        )
        classifier = FakeClassifier(route_result)
        runner = FakeRunner()
        tool = SopRunnerAdapter.sop_execute(
            sops=[sop],
            classifier=classifier,
            runner=runner,
        )

        result = tool.handler(sop_query="计算码头前沿水深 T=12.8 Z0=0.5")

        self.assertEqual(classifier.last_query, "计算码头前沿水深 T=12.8 Z0=0.5")
        self.assertEqual(len(runner.run_sop_calls), 1)
        self.assertEqual(result["sop_id"], "sop-berth-depth")
        self.assertEqual(result["final_context"]["depth"], 15.2)
        self.assertEqual(result["steps"][0]["status"], "success")
        self.assertEqual(result["sop_trace"][0]["step_id"], "s1")
        self.assertIn("成功 1 步", result["summary"])

    def test_run_sop_receives_route_args_and_handler_args(self):
        sop = make_sop()
        route_result = RouteResult(
            sop=sop,
            args={"T": 12.8},
            reason="matched",
            confidence=0.9,
            candidates=[],
        )
        runner = FakeRunner()
        tool = SopRunnerAdapter.sop_execute(
            sops=[sop],
            classifier=FakeClassifier(route_result),
            runner=runner,
        )

        tool.handler(sop_query="计算码头水深", args={"Z0": 0.5})

        _sop, initial_context = runner.run_sop_calls[0]
        self.assertEqual(initial_context["user_query"], "计算码头水深")
        self.assertEqual(initial_context["T"], 12.8)
        self.assertEqual(initial_context["Z0"], 0.5)

    def test_no_match_returns_error_and_does_not_run_sop(self):
        route_result = RouteResult(
            sop=None,
            args={},
            reason="不属于任何已知 SOP",
            confidence=0.2,
            candidates=[],
        )
        runner = FakeRunner()
        tool = SopRunnerAdapter.sop_execute(
            sops=[make_sop()],
            classifier=FakeClassifier(route_result),
            runner=runner,
        )

        result = tool.handler(sop_query="随便问问")

        self.assertIn("error", result)
        self.assertEqual(result["confidence"], 0.2)
        self.assertEqual(runner.run_sop_calls, [])

    def test_missing_sop_query_returns_error(self):
        tool = SopRunnerAdapter.sop_execute(sops=[make_sop()])
        result = tool.handler(sop_query=None)
        self.assertIn("error", result)

    def test_sop_loader_path_loads_published_sops(self):
        sop = make_sop()
        loader = Mock(load_all=Mock(return_value=[sop]))
        runner = FakeRunner()

        class StubClassifier:
            def __init__(self, sops, llm_client=None):
                self.sops = sops

            def route(self, user_query, config_name=None, mode="instruct"):
                return RouteResult(
                    sop=self.sops[0],
                    args={},
                    reason="matched",
                    confidence=0.9,
                    candidates=[],
                )

        tool = SopRunnerAdapter.sop_execute(
            sop_loader=loader,
            runner=runner,
        )
        with patch("angineer_core.classifier.IntentClassifier", StubClassifier):
            result = tool.handler(sop_query="计算码头前沿水深")

        loader.load_all.assert_called_once()
        self.assertEqual(result["sop_id"], "sop-berth-depth")

    def test_only_published_sops_passed_to_internal_classifier(self):
        draft = make_sop(status="draft")
        published = make_sop(status="published")
        built = []

        class CapturingClassifier:
            def __init__(self, sops, llm_client=None):
                built.append(sops)

            def route(self, user_query, config_name=None, mode="instruct"):
                return RouteResult(sop=None, args={}, reason="no match", confidence=0.0, candidates=[])

        tool = SopRunnerAdapter.sop_execute(
            sops=[draft, published],
            runner=FakeRunner(),
        )
        with patch("angineer_core.classifier.IntentClassifier", CapturingClassifier):
            tool.handler(sop_query="计算码头前沿水深")

        self.assertEqual(len(built), 1)
        self.assertEqual([sop.id for sop in built[0]], ["sop-berth-depth"])


class SopExecuteAgentToolContractTests(unittest.TestCase):
    def test_sop_execute_agent_tool_contract(self):
        tool = SopRunnerAdapter.sop_execute()
        self.assertEqual(tool.name, "sop_execute")
        self.assertFalse(tool.read_only)
        self.assertEqual(tool.execution_mode, "sequential")
        self.assertEqual(tool.timeout_s, 300)
        self.assertEqual(tool.parameters_schema["required"], ["sop_query"])


if __name__ == "__main__":
    unittest.main()
