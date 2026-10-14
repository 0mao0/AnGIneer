"""SOP 流程图快照通道测试（2026-10-14 业主需求：聊天 SSE 里可见 SOP 步骤流）。

契约：sop_execute 带 sop_event 通道时发 plan→step→done 三种快照，payload 自足
（前端只做替换式渲染）；不带通道的调用方（评测/REST/池化）行为逐位不变。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))

from angineer_core.agent_tools import SopRunnerAdapter  # noqa: E402
from angineer_core.base_contracts import RouteResult, SOP, Step  # noqa: E402


def make_sop():
    return SOP(
        id="sop-berth-width",
        name_zh="码头泊位宽度计算",
        steps=[
            Step(id="s1", name_zh="查表取船宽", tool="table_lookup", inputs={}),
            Step(id="s2", name_zh="代入公式", tool="calculator", inputs={}),
        ],
    )


class FakeClassifier:
    def __init__(self, sop):
        self._sop = sop

    def route(self, user_query, config_name=None, mode="instruct"):
        return RouteResult(sop=self._sop, args={}, reason="命中", confidence=0.9)


class FakeMemory:
    blackboard = {"W": 310.0}
    history: list = []


class FakeRunner:
    """按真实语义触发 step_callback 的假执行器（run_sop 签名兼容）。"""

    def __init__(self):
        self.memory = FakeMemory()
        self.step_durations = {}

    def run_sop(self, sop, initial_context, pre_logs=None, step_callback=None):
        if step_callback is not None:
            step_callback({"step_id": "s1", "step_name": "查表取船宽", "status": "success", "duration": 0.4})
            step_callback({"step_id": "s2", "step_name": "代入公式", "status": "failed",
                           "duration": 1.0, "error": "缺参 W"})
        return {"W": 310.0}


class SopFlowEventTests(unittest.TestCase):
    def _run(self, with_channel: bool):
        sop = make_sop()
        events = []
        tool = SopRunnerAdapter.sop_execute(
            sops=[sop],
            classifier=FakeClassifier(sop),
            runner=FakeRunner(),
            sop_event=(events.append if with_channel else None),
        )
        result = tool.handler(sop_query="某泊位宽度计算")
        return events, result

    def test_plan_step_done_snapshot_sequence(self):
        events, result = self._run(with_channel=True)
        # plan：执行前全 pending 骨架
        self.assertEqual(events[0]["running"], True)
        self.assertEqual(events[0]["sop_id"], "sop-berth-width")
        self.assertEqual(events[0]["sop_name"], "码头泊位宽度计算")
        self.assertEqual(events[0]["total"], 2)
        self.assertEqual(events[0]["done"], 0)
        self.assertEqual([s["status"] for s in events[0]["steps"]], ["pending", "pending"])
        self.assertEqual([s["step_name"] for s in events[0]["steps"]], ["查表取船宽", "代入公式"])
        # step 事件逐步回填状态与耗时
        self.assertEqual(events[1]["done"], 1)
        self.assertEqual(events[1]["steps"][0]["status"], "success")
        self.assertEqual(events[1]["steps"][0]["duration_ms"], 400)
        self.assertEqual(events[2]["steps"][1]["status"], "failed")
        self.assertEqual(events[2]["steps"][1]["error"], "缺参 W")
        # done：running=False，状态保持
        self.assertEqual(events[-1]["running"], False)
        self.assertEqual(events[-1]["done"], 2)
        # 返回结果不受通道影响（steps/sop_trace 仍在）
        self.assertEqual(result["sop_id"], "sop-berth-width")
        self.assertIn("steps", result)

    def test_without_channel_is_byte_identical(self):
        with_channel, result_with = self._run(with_channel=True)
        _, result_without = self._run(with_channel=False)
        self.assertEqual(result_with, result_without)
        self.assertEqual(len(with_channel) >= 4, True)


if __name__ == "__main__":
    unittest.main()
