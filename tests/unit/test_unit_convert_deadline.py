"""LibreOffice convert timeout must survive system sleep (Modern Standby)."""
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "services" / "docs-core" / "src"))

from docs_core.step02_convert2pdf.convert2pdf import _ConvertDeadline  # noqa: E402


class ConvertDeadlineTest(unittest.TestCase):
    def test_expires_after_timeout_of_monotonic_time(self):
        ticks = [0.0]
        deadline = _ConvertDeadline(timeout=10, clock=lambda: ticks[0], wall=lambda: 100.0)
        self.assertFalse(deadline.poll_expired())
        ticks[0] = 10.1
        self.assertTrue(deadline.poll_expired())

    def test_wake_after_sleep_resets_deadline(self):
        ticks = [0.0]
        wall = [100.0]
        deadline = _ConvertDeadline(timeout=10, clock=lambda: ticks[0], wall=lambda: wall[0])
        ticks[0] = 50.0   # monotonic advanced past the old deadline
        wall[0] = 1000.0  # wall clock jumped forward: machine was asleep
        self.assertFalse(deadline.poll_expired())  # deadline reset on wake
        ticks[0] = 60.1   # another full timeout of active time
        self.assertTrue(deadline.poll_expired())

    def test_small_wall_jump_does_not_reset(self):
        ticks = [0.0]
        wall = [100.0]
        deadline = _ConvertDeadline(timeout=10, clock=lambda: ticks[0], wall=lambda: wall[0])
        ticks[0] = 10.1
        wall[0] = 110.0  # 10s wall jump, below the sleep threshold
        self.assertTrue(deadline.poll_expired())


if __name__ == "__main__":
    unittest.main()
