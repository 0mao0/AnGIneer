"""L3 LLM 流式首字存活检查（2026-10-05 需求：600s 挂起判定线之下的用户可见等待收口）。

背景：ANGINEER_TIMEOUT_TOTAL=600 之后，上游挂起（连接活着但永不回数据）时，
generator 会阻塞在第一次 __next__，httpx 的 read 超时与循环里的 cancel 检查都碰不到它
（main.py:564 注释实锤：客户端 abort 只断开连接，服务端要等 LLM 调用退出）。
本测试锁四条语义：
  a) 首字前挂起 → 存活线到点击断拉流，本轮按异常降级收口，不阻塞、不挂起；
  b) 慢而活跃（chunk 间隔小于存活线）→ 不杀；
  c) 首字之后的间隙不归存活线管（read 超时管）；
  d) 0 = 禁用 → 零开销，挂起由 read 超时兜底。
"""
import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))

from angineer_core.agent_loop import AgentLoopConfig, _iter_with_liveness, _run_llm_turn  # noqa: E402
from angineer_core.tool_codec import TextToolCallCodec  # noqa: E402

from agent_test_utils import MockLLM, text_events  # noqa: E402


class _HangingGenerator:
    """无限阻塞的假流：__next__ 永不返回（模拟上游挂起、连接不碎）。"""

    def __init__(self):
        self.abandoned = threading.Event()

    def __iter__(self):
        return self

    def __next__(self):
        self.abandoned.wait()
        raise StopIteration


class IterWithLivenessTests(unittest.TestCase):
    def test_reaps_hanging_iterator_before_first_item(self):
        hung = _HangingGenerator()
        t0 = time.monotonic()
        with self.assertRaises(RuntimeError) as ctx:
            for _ in _iter_with_liveness(iter(hung), 0.2):
                pass
        elapsed = time.monotonic() - t0
        # 0.2s 线 + 调度余量；远小于挂起等待，证明阻塞点被移出了当前线程
        self.assertLess(elapsed, 1.5)
        self.assertIn("挂起", str(ctx.exception))
        # 线程被显式放弃，不等 hung 解除
        self.assertFalse(hung.abandoned.is_set())

    def test_active_stream_not_killed(self):
        def active():
            for i in range(3):
                time.sleep(0.1)
                yield {"type": "delta", "text": str(i)}
            yield {"type": "done", "finish_reason": "stop", "usage": None}

        out = list(_iter_with_liveness(active(), 0.5))
        self.assertEqual([e["type"] for e in out], ["delta", "delta", "delta", "done"])

    def test_disabled_still_pumps_events(self):
        """禁用存活线（limit_s=0）≠ 原样透传：事件照常逐帧消费（cancel 维度常驻）。"""
        events = list(text_events("答案"))
        llm = MockLLM(lambda messages, kwargs: iter(events))
        out = list(_iter_with_liveness(llm.chat_stream_events([]), 0))
        self.assertEqual([e["type"] for e in out], ["delta", "done"])

    def test_cancel_responds_even_when_liveness_disabled(self):
        """禁用存活线但传 cancel：挂起中 set cancel 应很快静默收口（修 10-05
        透传分支吞 cancel 的 bug——挂起 + 禁用组合正是停止按钮的真实场景）。"""
        hung = _HangingGenerator()
        cancel = threading.Event()
        threading.Thread(target=lambda: (time.sleep(0.2), cancel.set()), daemon=True).start()
        t0 = time.monotonic()
        out = list(_iter_with_liveness(iter(hung), 0, cancel))
        self.assertEqual(out, [])
        self.assertLess(time.monotonic() - t0, 2.0)

    def test_after_first_item_gaps_are_not_liveness_domain(self):
        """首字后的长间隙不杀——生成段由 read 超时管，存活线只管首字。"""
        def slow_tail():
            yield {"type": "delta", "text": "a"}
            time.sleep(0.4)
            yield {"type": "done", "finish_reason": "stop", "usage": None}

        out = list(_iter_with_liveness(slow_tail(), 0.15))
        self.assertEqual([e["type"] for e in out], ["delta", "done"])

    def test_body_error_propagates(self):
        def raising():
            yield {"type": "delta", "text": "a"}
            raise ValueError("上游炸了")

        gen = _iter_with_liveness(raising(), 5)
        next(gen)
        with self.assertRaises(ValueError):
            next(gen)


class RunLlmTurnLivenessTests(unittest.TestCase):
    def test_hang_before_first_token_raises_not_blocks(self):
        hung = _HangingGenerator()
        llm = MockLLM(lambda messages, kwargs: hung)
        errors: list = []
        config = AgentLoopConfig(
            llm=llm, tools=[], system_prompt="你是助手", max_turns=1,
            codec=TextToolCallCodec(), error_sink=errors, first_token_liveness_s=0.2,
        )
        t0 = time.monotonic()
        assistant, calls, direct, usage = _run_llm_turn(
            [], [], config, TextToolCallCodec(), {}, None,
            "run-test", threading.Event(), 0, False,
        )
        elapsed = time.monotonic() - t0
        self.assertLess(elapsed, 2.0, "挂起未被存活线收口——阻塞点没移出当前线程")
        self.assertTrue(any("流式调用异常" in e for e in errors), f"error_sink 应留痕: {errors}")
        self.assertEqual(assistant.content, "")
        # 拉流线程被显式放弃（hung 从未解除），但当前线程已收回控制权

    def test_active_turn_streams_through(self):
        """开线后正常流不受伤：delta 全收、full_text 完整。"""
        llm = MockLLM(lambda messages, kwargs: text_events("部分答案"))
        errors: list = []
        config = AgentLoopConfig(
            llm=llm, tools=[], system_prompt="你是助手", max_turns=1,
            codec=TextToolCallCodec(), error_sink=errors, first_token_liveness_s=5,
        )
        assistant, calls, direct, usage = _run_llm_turn(
            [], [], config, TextToolCallCodec(), {}, None,
            "run-test", threading.Event(), 0, False,
        )
        self.assertEqual(assistant.content, "部分答案")
        self.assertEqual(errors, [])

    def test_cancel_while_hanging_returns_promptly(self):
        """停止按钮 = 等待期 cancel 可响应：挂起中 set cancel，本轮应很快收口，
        不等存活线（main.py:564 实锤的『服务端要等 LLM 调用退出』由此收口）。"""
        hung = _HangingGenerator()
        llm = MockLLM(lambda messages, kwargs: hung)
        config = AgentLoopConfig(
            llm=llm, tools=[], system_prompt="你是助手", max_turns=1,
            codec=TextToolCallCodec(), first_token_liveness_s=0,  # 禁用时靠 cancel 分支
        )
        cancel = threading.Event()

        def _set_later():
            time.sleep(0.2)
            cancel.set()

        threading.Thread(target=_set_later, daemon=True).start()
        t0 = time.monotonic()
        _run_llm_turn(
            [], [], config, TextToolCallCodec(), {}, None,
            "run-test", cancel, 0, False,
        )
        self.assertLess(time.monotonic() - t0, 2.0)


if __name__ == "__main__":
    unittest.main()


if __name__ == "__main__":
    unittest.main()
