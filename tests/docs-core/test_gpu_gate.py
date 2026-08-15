"""回归测试：多 ParseOrchestrator 实例共享全局序号，GPU 闸门不误伤本地上传路径任务。

根因（V1）：每实例独立 counter 从 1 发号 + 模块级共享 gate，
导致后活跃实例的任务 seq < gate._next_seq 被误判"排队期间被取消"。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-core/src")))

from docs_core.parse_pipeline import _FifoGpuGate, ParseOrchestrator  # noqa: E402


class SharedArrivalCounterTests(unittest.TestCase):
    def test_two_orchestrators_share_global_counter(self):
        o1 = ParseOrchestrator()
        o2 = ParseOrchestrator()
        self.assertIs(o1._arrival_counter, o2._arrival_counter)

    def test_interleaved_seqs_from_two_orchestrators_are_monotonic(self):
        o1 = ParseOrchestrator()
        o2 = ParseOrchestrator()
        seqs = [next(o1._arrival_counter), next(o2._arrival_counter), next(o1._arrival_counter)]
        self.assertEqual(seqs, sorted(seqs))
        self.assertEqual(len(set(seqs)), 3)


class LateSeqFallbackTests(unittest.TestCase):
    def test_late_seq_acquires_when_token_available(self):
        """晚到序号（seq < next_seq）在令牌空闲时放行，不再抛取消异常。"""
        gate = _FifoGpuGate(1)
        gate.acquire(1)  # 正常获取，_next_seq -> 2
        gate.release()
        gate.acquire(1)  # 重复/晚到序号：放行，不抛异常
        gate.release()

    def test_late_seq_waits_when_token_busy(self):
        """晚到序号在令牌占用时不得插队（等待而非放行）。"""
        import threading
        import time

        gate = _FifoGpuGate(1)
        gate.acquire(1)  # _next_seq -> 2, tokens -> 0
        acquired = []

        def _late():
            gate.acquire(1)  # 晚到序号，tokens=0 时应等待
            acquired.append(True)

        t = threading.Thread(target=_late, daemon=True)
        t.start()
        time.sleep(0.6)
        self.assertEqual(acquired, [])
        gate.release()
        t.join(timeout=2)
        self.assertEqual(acquired, [True])


if __name__ == "__main__":
    unittest.main()
