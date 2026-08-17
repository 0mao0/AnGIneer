"""熔断器状态机与可观测性测试。"""

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SRC = TESTS_DIR.parent / "src"
for p in (str(SRC), str(TESTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from ai_inference.llm_client import CircuitBreaker, CircuitState
from ai_inference.llm_config import CircuitBreakerConfig


class TestCircuitBreakerStateMachine(unittest.TestCase):
    def test_closed_to_open_after_threshold(self):
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=3, recovery_timeout=60.0))
        for _ in range(3):
            cb.record_failure(ValueError("boom"))
        self.assertEqual(cb.state, CircuitState.OPEN)
        self.assertFalse(cb.can_execute())
        self.assertEqual(cb.get_status()["failure_count"], 3)

    def test_open_recovers_to_half_open_after_timeout(self):
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=1, recovery_timeout=60.0))
        cb.record_failure(ValueError("boom"))
        cb.last_failure_time = datetime.now() - timedelta(seconds=61)
        self.assertTrue(cb.can_execute())
        self.assertEqual(cb.state, CircuitState.HALF_OPEN)

    def test_half_open_success_recloses(self):
        cb = CircuitBreaker(
            CircuitBreakerConfig(failure_threshold=1, recovery_timeout=60.0, half_open_requests=2)
        )
        cb.record_failure(ValueError("boom"))
        cb.last_failure_time = datetime.now() - timedelta(seconds=61)
        self.assertTrue(cb.can_execute())
        cb.record_success()
        self.assertEqual(cb.state, CircuitState.HALF_OPEN)
        cb.record_success()
        self.assertEqual(cb.state, CircuitState.CLOSED)
        self.assertEqual(cb.get_status()["failure_count"], 0)

    def test_half_open_failure_reopens(self):
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=1, recovery_timeout=60.0))
        cb.record_failure(ValueError("first"))
        cb.last_failure_time = datetime.now() - timedelta(seconds=61)
        self.assertTrue(cb.can_execute())
        cb.record_failure(ValueError("second"))
        self.assertEqual(cb.state, CircuitState.OPEN)
        self.assertEqual(cb.get_status()["last_error_message"], "second")


class TestCircuitBreakerObservability(unittest.TestCase):
    def test_status_includes_counts_and_last_errors(self):
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=5, recovery_timeout=60.0))
        cb.record_failure(ValueError("first boom"))
        cb.record_failure(ValueError("second boom"))
        cb.record_success()
        status = cb.get_status()
        for key in (
            "state",
            "failure_count",
            "success_count",
            "half_open_success_count",
            "total_calls",
            "last_failure_time",
            "last_error_message",
            "last_success_time",
        ):
            self.assertIn(key, status)
        self.assertEqual(status["total_calls"], 3)
        self.assertEqual(status["success_count"], 1)
        self.assertEqual(status["last_error_message"], "second boom")

    def test_closed_success_resets_failure_count(self):
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=5, recovery_timeout=60.0))
        cb.record_failure(ValueError("boom"))
        cb.record_success()
        self.assertEqual(cb.get_status()["failure_count"], 0)


if __name__ == "__main__":
    unittest.main()
