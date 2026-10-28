"""单测：GPU 闸门按「到达本闸门」先后排队（2026-10-14 语义修订，v0.2.98 上线；任务序号仅作身份键）。"""
import sys
import threading
import time
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "services" / "docs-core" / "src"))

from docs_core.parse_pipeline import ParseTaskCancelledError, _FifoGpuGate


class FifoGpuGateTest(unittest.TestCase):
    def test_serves_by_arrival_at_gate_not_submission_seq(self):
        """新语义钉板：先到本闸门者先获槽，任务序号不参与排序（旧契约「按序号放行」已废）。

        到达顺序固定 3 → 2 → 1（序号与到达相反），放行后必须按到达序 2、1 服务。
        """
        gate = _FifoGpuGate(max_concurrency=1)
        order = []
        lock = threading.Lock()

        def worker(seq):
            gate.acquire(seq)
            with lock:
                order.append(seq)
            time.sleep(0.05)
            gate.release()

        gate.acquire(3)  # 最早到达者持槽
        t2 = threading.Thread(target=worker, args=(2,))
        t2.start()
        time.sleep(0.2)  # 确保 2 先于 1 领到排队号（到达序确定）
        t1 = threading.Thread(target=worker, args=(1,))
        t1.start()
        time.sleep(0.2)
        gate.release()  # 3 让位 → 按到达序轮到 2，序号最小的 1 不得插队
        t1.join(timeout=5)
        t2.join(timeout=5)
        self.assertEqual(order, [2, 1])

    def test_cancelled_waiter_is_skipped(self):
        gate = _FifoGpuGate(max_concurrency=1)
        gate.acquire(1)
        acquired = []
        lock = threading.Lock()

        def cancelled_worker():
            def cancel_check():
                raise ParseTaskCancelledError("取消")
            with self.assertRaises(ParseTaskCancelledError):
                gate.acquire(2, cancel_check=cancel_check)

        def later_worker():
            gate.acquire(3)
            with lock:
                acquired.append(3)
            gate.release()

        t2 = threading.Thread(target=cancelled_worker)
        t3 = threading.Thread(target=later_worker)
        t2.start()
        t3.start()
        time.sleep(0.2)
        gate.release()  # 放行 1，之后应轮到 3（2 已被取消让位）
        t2.join(timeout=5)
        t3.join(timeout=5)
        self.assertEqual(acquired, [3])

    def test_should_wait_reflects_turn_and_tokens(self):
        gate = _FifoGpuGate(max_concurrency=1)
        self.assertFalse(gate.should_wait(1))  # 空闸：新到者即队首，不按任务序号排队（新语义）
        gate.acquire(1)
        self.assertTrue(gate.should_wait(2))  # 队首轮到但令牌被占
        gate.release()
        self.assertFalse(gate.should_wait(2))

    def test_acquire_late_seq_passes_when_token_available(self):
        gate = _FifoGpuGate(max_concurrency=1)
        gate.acquire(1)
        gate.release()
        gate.acquire(2)
        gate.release()
        # 序号 1、2 已过，晚到/重复序号在令牌空闲时兜底放行（不误伤任务），
        # 修复多 ParseOrchestrator 实例下误报"排队期间被取消"的根因。
        gate.acquire(1)
        gate.release()


    def test_skip_fills_hole_left_by_failed_pre_gate_task(self):
        gate = _FifoGpuGate(max_concurrency=1)
        # Task 1 failed before reaching the gate (e.g. convert timeout) and never
        # called acquire(); task 2 must proceed after skip(1), not queue forever.
        gate.skip(1)
        self.assertFalse(gate.should_wait(2))
        gate.acquire(2)
        gate.release()

    def test_skip_is_noop_for_seq_that_already_acquired(self):
        gate = _FifoGpuGate(max_concurrency=1)
        gate.acquire(1)
        # A task that already acquired the slot must not advance the queue twice.
        gate.skip(1)
        self.assertTrue(gate.should_wait(2))  # seq 2 still waits for token release
        gate.release()
        self.assertFalse(gate.should_wait(2))
        gate.acquire(2)
        gate.release()


class ParseTaskExitSkipsGateTest(unittest.TestCase):
    def test_pipeline_failure_before_gate_skips_arrival_seq(self):
        from unittest.mock import MagicMock, patch

        from docs_core import parse_pipeline as pp

        gate = _FifoGpuGate(max_concurrency=1)
        ks = MagicMock()
        ks.meta_store = MagicMock()
        ks.get_node.return_value = MagicMock(file_path="a.docx")

        with patch.object(pp, "_MINERU_GPU_GATE", gate), \
                patch.object(pp, "get_docs_service", return_value=ks), \
                patch.object(pp, "run_pipeline", side_effect=RuntimeError("convert timeout")):
            orch = pp.ParseOrchestrator()
            orch._parsers["task-x"] = MagicMock()
            orch._run_parse_task("task-x", "lib", "doc1", "a.docx", {}, arrival_seq=1)

        # seq=1 failed before reaching the gate; seq=2 must be able to proceed.
        self.assertFalse(gate.should_wait(2))
        gate.acquire(2)
        gate.release()


if __name__ == "__main__":
    unittest.main()
