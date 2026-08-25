import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../scripts")))

from open_ragbench import import_kb  # noqa: E402
from open_ragbench import common  # noqa: E402


class ImportKbTests(unittest.TestCase):
    def test_advance_state_sets_status(self):
        state = {"library_id": "", "papers": {}}
        state = import_kb.advance_state(state, "p1", "d1", "succeeded", "")
        self.assertEqual(state["papers"]["p1"]["status"], "succeeded")
        self.assertEqual(state["papers"]["p1"]["retries"], 0)

    def test_advance_state_increments_retries_on_failure(self):
        state = import_kb.advance_state({"papers": {}}, "p1", "", "failed", "boom")
        state = import_kb.advance_state(state, "p1", "", "failed", "boom")
        self.assertEqual(state["papers"]["p1"]["retries"], 2)

    def test_run_import_retries_three_times(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_dir = Path(tmp)
            (pdf_dir / "p1.pdf").write_bytes(b"%PDF-1.4 fake")
            manifest = {"papers": [{"paper_id": "p1", "url": "u", "is_hard_negative": False}]}
            with patch.object(import_kb, "login_admin", return_value="tok"), \
                 patch.object(import_kb, "create_library", return_value="lib-1"), \
                 patch.object(import_kb, "create_key", return_value="key-1"), \
                 patch.object(import_kb, "upload_pdf", return_value="d1") as mock_upload, \
                 patch.object(import_kb, "poll_status", return_value="failed"):
                state, api_key = import_kb.run_import(
                    common.Endpoints(), "admin", "pw", manifest, {"library_id": "", "papers": {}},
                    pdf_dir=pdf_dir, poll_interval=0,
                )
            self.assertEqual(mock_upload.call_count, 3)
            self.assertEqual(state["papers"]["p1"]["status"], "failed")
            self.assertEqual(api_key, "key-1")

    def test_run_import_create_only_skips_upload(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_dir = Path(tmp)
            (pdf_dir / "p1.pdf").write_bytes(b"%PDF-1.4 fake")
            manifest = {"papers": [{"paper_id": "p1", "url": "u", "is_hard_negative": False}]}
            with patch.object(import_kb, "login_admin", return_value="tok"), \
                 patch.object(import_kb, "create_library", return_value="lib-1"), \
                 patch.object(import_kb, "create_key", return_value="key-1"), \
                 patch.object(import_kb, "upload_pdf", return_value="d1") as mock_upload, \
                 patch.object(import_kb, "poll_status", return_value="succeeded"):
                state, api_key = import_kb.run_import(
                    common.Endpoints(), "admin", "pw", manifest, {"library_id": "", "papers": {}},
                    pdf_dir=pdf_dir, create_only=True,
                )
            mock_upload.assert_not_called()
            self.assertEqual(state["library_id"], "lib-1")
            self.assertEqual(api_key, "key-1")

    def test_run_import_accepts_partial_as_terminal(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_dir = Path(tmp)
            (pdf_dir / "p1.pdf").write_bytes(b"%PDF-1.4 fake")
            manifest = {"papers": [{"paper_id": "p1", "url": "u", "is_hard_negative": False}]}
            with patch.object(import_kb, "login_admin", return_value="tok"), \
                 patch.object(import_kb, "create_library", return_value="lib-1"), \
                 patch.object(import_kb, "create_key", return_value="key-1"), \
                 patch.object(import_kb, "upload_pdf", return_value="d1") as mock_upload, \
                 patch.object(import_kb, "poll_status", return_value="partial"):
                state, _ = import_kb.run_import(
                    common.Endpoints(), "admin", "pw", manifest, {"library_id": "", "papers": {}},
                    pdf_dir=pdf_dir, poll_interval=0,
                )
            self.assertEqual(mock_upload.call_count, 1)
            self.assertEqual(state["papers"]["p1"]["status"], "partial")


if __name__ == "__main__":
    unittest.main()
