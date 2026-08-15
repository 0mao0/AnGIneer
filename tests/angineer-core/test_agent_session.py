"""P2 AgentSession 单测：单飞、steer、follow_up、cancel、wait_for_idle。"""
import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))

from angineer_core.agent_loop import AgentLoopConfig  # noqa: E402
from angineer_core.agent_session import AgentSession  # noqa: E402
from angineer_core.agent_tools import AgentTool  # noqa: E402

from agent_test_utils import MockLLM, text_events, tool_block  # noqa: E402


def search_tool(handler):
    return AgentTool(
        name="search",
        description="检索",
        parameters_schema={"type": "object", "properties": {}},
        handler=handler,
    )


class AgentSessionTests(unittest.TestCase):
    def test_run_appends_history_and_returns_new_messages(self):
        llm = MockLLM(lambda messages, kwargs: text_events("答案"))
        session = AgentSession(lambda: AgentLoopConfig(llm=llm, tools=[], system_prompt="p"))
        added = session.run("问题")

        self.assertEqual(added[-1].content, "答案")
        self.assertEqual(session.history[0].role, "user")
        self.assertEqual(session.history[0].content, "问题")
        self.assertEqual(session.history[-1].content, "答案")
        self.assertTrue(session.wait_for_idle(timeout=1))

    def test_active_run_single_flight(self):
        started = threading.Event()
        release = threading.Event()

        def slow():
            started.set()
            release.wait(2)
            return {"ok": True}

        llm = MockLLM(lambda messages, kwargs: text_events(tool_block([{"name": "search", "arguments": {}}])))
        session = AgentSession(lambda: AgentLoopConfig(llm=llm, tools=[search_tool(slow)], system_prompt="p"))

        errors = []

        def run_in_thread():
            try:
                session.run("第一个")
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        thread = threading.Thread(target=run_in_thread)
        thread.start()
        self.assertTrue(started.wait(2))

        with self.assertRaises(RuntimeError):
            session.run("并发第二个")

        release.set()
        thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])

    def test_steer_injected_at_next_turn_boundary(self):
        entered_tool = threading.Event()
        allow_return = threading.Event()
        seen_steer = threading.Event()

        def slow():
            entered_tool.set()
            allow_return.wait(2)
            return {"ok": True}

        def handler(messages, kwargs):
            if len(llm.calls) == 1:
                yield from text_events(tool_block([{"name": "search", "arguments": {}}]))
            else:
                for msg in messages:
                    if msg.get("role") == "user" and "补充约束" in msg.get("content", ""):
                        seen_steer.set()
                yield from text_events("最终")

        llm = MockLLM(handler)
        session = AgentSession(lambda: AgentLoopConfig(llm=llm, tools=[search_tool(slow)], system_prompt="p"))
        result_holder = {}

        def run_in_thread():
            result_holder["added"] = session.run("问题")

        thread = threading.Thread(target=run_in_thread)
        thread.start()
        self.assertTrue(entered_tool.wait(2))
        session.steer("补充约束")
        allow_return.set()
        thread.join(3)

        self.assertTrue(seen_steer.is_set())
        self.assertEqual(result_holder["added"][-1].content, "最终")

    def test_follow_up_queued_into_next_run(self):
        llm = MockLLM(lambda messages, kwargs: text_events("答案"))
        session = AgentSession(lambda: AgentLoopConfig(llm=llm, tools=[], system_prompt="p"))
        session.run("第一问")
        session.follow_up("继续展开")
        session.run("第二问")

        user_contents = [m.content for m in session.history if m.role == "user"]
        self.assertIn("继续展开", user_contents)
        self.assertIn("第二问", user_contents)
        self.assertLess(user_contents.index("继续展开"), user_contents.index("第二问"))

    def test_cancel_and_wait_for_idle(self):
        entered = threading.Event()
        release = threading.Event()

        def slow():
            entered.set()
            release.wait(2)
            return {"ok": True}

        llm = MockLLM(lambda messages, kwargs: text_events(tool_block([{"name": "search", "arguments": {}}])))
        session = AgentSession(lambda: AgentLoopConfig(llm=llm, tools=[search_tool(slow)], system_prompt="p"))
        events = []

        def run_in_thread():
            session.run("问题", emit=events.append)

        thread = threading.Thread(target=run_in_thread)
        thread.start()
        self.assertTrue(entered.wait(2))
        session.cancel()
        release.set()

        self.assertTrue(session.wait_for_idle(timeout=3))
        thread.join(3)
        self.assertEqual(events[-1].payload["reason"], "cancelled")


if __name__ == "__main__":
    unittest.main()
