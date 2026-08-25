"""MinerU 公司网关：大文件分块触发与 5xx 瞬时重试。"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from docs_core.step03_mineru_parse.mineru_parser import MinerUParser  # noqa: E402


MINIMAL_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
    b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n"
    b"0000000058 00000 n \n0000000115 00000 n \n"
    b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n190\n%%EOF\n"
)


class MineruCompanyApiTimeoutTests(unittest.TestCase):
    def test_large_file_triggers_size_chunking(self):
        parser = MinerUParser()
        called = {}

        def fake_chunks(input_path, output_dir, page_count, chunk_size):
            called["page_count"] = page_count
            called["chunk_size"] = chunk_size
            return {"success": True, "page_count": page_count}

        parser._parse_large_pdf_in_chunks = fake_chunks
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "big.pdf"
            pdf.write_bytes(MINIMAL_PDF)
            with patch.dict(os.environ, {"MINERU_SYNC_MAX_BYTES": "100"}, clear=False):
                result = parser._parse_document(str(pdf), tmp)
        self.assertTrue(result["success"])
        self.assertIn("chunk_size", called)

    def test_small_file_goes_single(self):
        parser = MinerUParser()
        called = {}
        parser._parse_single_file = lambda *a, **k: {"success": True}
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "small.pdf"
            pdf.write_bytes(MINIMAL_PDF)
            with patch.dict(os.environ, {"MINERU_SYNC_MAX_BYTES": str(1 << 30)}, clear=False):
                result = parser._parse_document(str(pdf), tmp)
        self.assertTrue(result["success"])

    def test_504_retries_then_fails(self):
        parser = MinerUParser()
        calls = {"n": 0}

        class FakeResp:
            status_code = 504
            text = "<html>504 Gateway Time-out</html>"
            content = b""

        def fake_request(method, url, **kwargs):
            calls["n"] += 1
            return FakeResp()

        parser._request_with_proxy_fallback = fake_request
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "a.pdf"
            pdf.write_bytes(MINIMAL_PDF)
            with patch("time.sleep"):
                result = parser._parse_single_file(str(pdf), tmp)
        self.assertFalse(result["success"])
        self.assertIn("504", result["error"])
        self.assertEqual(calls["n"], 3)


if __name__ == "__main__":
    unittest.main()
