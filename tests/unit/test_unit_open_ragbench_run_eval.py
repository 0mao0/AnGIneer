import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../scripts")))

from open_ragbench import run_eval  # noqa: E402
from open_ragbench import common  # noqa: E402


class RunEvalTests(unittest.TestCase):
    def test_run_eval_imports_then_starts_then_polls(self):
        run = {"run_id": "r1", "status": "completed", "summary_scores": {}}
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "raw.json"
            with patch.object(run_eval, "import_dataset") as imp, \
                 patch.object(run_eval, "start_run", return_value="r1") as start, \
                 patch.object(run_eval, "poll_run", return_value=run):
                result = run_eval.run_eval(common.Endpoints(), out_path=out_path, poll_interval=0)
            imp.assert_called_once()
            start.assert_called_once()
            self.assertEqual(result["run_id"], "r1")
            self.assertTrue(out_path.exists())


if __name__ == "__main__":
    unittest.main()
