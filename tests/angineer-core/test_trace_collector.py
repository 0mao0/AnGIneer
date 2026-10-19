"""阶段 6 测试：TraceCollector——agent 事件收集与 run 级投影的统一收口。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/ai-inference/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../angineer-core")))

from agent_test_utils import MockLLM, text_events  # noqa: E402
from angineer_core.agent_loop import AgentLoopConfig, run_agent_loop  # noqa: E402
from angineer_core.agent_messages import AgentMessage  # noqa: E402
from angineer_core.trace_collector import TraceCollector  # noqa: E402


class TraceCollectorTests(unittest.TestCase):
    def test_collects_events_and_projects_run_end(self):
        collector = TraceCollector()
        llm = MockLLM(lambda messages, kwargs: text_events("答案", "stop"))
        config = AgentLoopConfig(llm=llm, tools=[], system_prompt="p", max_turns=1)
        messages = [AgentMessage(role="user", content="q")]

        run_agent_loop(messages, config, emit=collector.emit, run_id="r1")

        types = [e.type for e in collector.events]
        self.assertEqual(types[0], "run_start")
        self.assertEqual(types[-1], "run_end")
        payload = collector.run_end_payload()
        self.assertEqual(payload["reason"], "completed")
        self.assertEqual(payload["turns"], 1)
        # 流式增量只服务聊天 SSE，入库 trace 不含 message_delta
        self.assertTrue(any(t == "message_delta" for t in types))
        dump = collector.agent_events_dump()
        self.assertFalse(any(e["type"] == "message_delta" for e in dump))
        self.assertEqual(dump[0]["type"], "run_start")
        self.assertEqual(dump[-1]["type"], "run_end")
        # run_end 的整段 messages 与 answer/工具全文重复，入库裁掉
        self.assertNotIn("messages", dump[-1]["payload"])
        self.assertNotIn("answer_pre_strip", dump[-1]["payload"])

    def test_trace_payload_has_version_events_and_summary(self):
        collector = TraceCollector()
        llm = MockLLM(lambda messages, kwargs: text_events("答案", "stop"))
        config = AgentLoopConfig(llm=llm, tools=[], system_prompt="p", max_turns=1)
        messages = [AgentMessage(role="user", content="q")]

        run_agent_loop(messages, config, emit=collector.emit, run_id="r1")

        trace = collector.trace_payload(duration_ms=1234)
        self.assertEqual(trace["version"], 1)
        self.assertEqual(trace["events"], collector.agent_events_dump())
        self.assertEqual(trace["summary"]["turns"], 1)
        self.assertEqual(trace["summary"]["tool_calls"], 0)
        self.assertEqual(trace["summary"]["duration_ms"], 1234)
        self.assertEqual(trace["summary"]["reason"], "completed")
        self.assertIn("final_outcome", trace["summary"])
        self.assertIsInstance(trace["summary"]["path_trace"], list)

    def test_run_end_payload_empty_when_no_events(self):
        collector = TraceCollector()
        self.assertEqual(collector.run_end_payload(), {})
        self.assertEqual(collector.agent_events_dump(), [])
        trace = collector.trace_payload()
        self.assertEqual(trace["events"], [])
        self.assertEqual(trace["summary"]["turns"], 0)
        self.assertEqual(trace["summary"]["tool_calls"], 0)


if __name__ == "__main__":
    unittest.main()
