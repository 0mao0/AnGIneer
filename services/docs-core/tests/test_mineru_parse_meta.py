"""MinerU 解析元数据：page_count / ocr_retried 传递契约。"""
import io
import os
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from docs_core.step03_mineru_parse.mineru_parser import MinerUParser  # noqa: E402


def _zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("content.md", "# title\n")
    return buf.getvalue()


class _FakeResp:
    def __init__(self, status_code: int, payload=None, content=b""):
        self.status_code = status_code
        self._payload = payload or {}
        self.content = content

    def json(self):
        return self._payload


class MineruParseMetaTests(unittest.TestCase):
    def test_parse_document_carries_page_count(self):
        parser = MinerUParser()
        with patch.object(parser, "_get_pdf_page_count", return_value=7), \
             patch.object(parser, "_parse_single_file", return_value={"success": True}):
            result = parser._parse_document("/tmp/x.pdf", "/tmp/out")
        self.assertEqual(result.get("page_count"), 7)

    def test_parse_to_raw_artifacts_carries_page_meta_into_persisted(self):
        parser = MinerUParser()
        canned = {
            "success": True,
            "page_count": 42,
            "ocr_retried": True,
        }
        with patch.object(parser, "parse_document", return_value=canned), \
             patch.object(parser, "_persist_to_doc", return_value={
                 "parsed_dir": "/tmp/x", "output_summary": "content.md", "has_images": False,
             }):
            result = parser.parse_to_raw_artifacts(
                "/tmp/x.pdf", output_dir="/tmp/mineru-out",
                library_id="lib1", doc_id="doc1",
            )
        persisted = result.get("persisted") or {}
        self.assertEqual(persisted.get("page_count"), 42)
        self.assertTrue(persisted.get("ocr_retried"))

    def test_ocr_retry_branch_marks_ocr_retried(self):
        parser = MinerUParser()
        parser.ocr_enabled = False
        responses = [
            _FakeResp(409, {"task_id": "t1", "status": "failed", "error": "no text layer"}),
            _FakeResp(200, content=_zip_bytes()),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = os.path.join(tmp, "x.pdf")
            with open(pdf_path, "wb") as f:
                f.write(b"%PDF-1.4\n")
            out_dir = os.path.join(tmp, "out")
            os.makedirs(out_dir, exist_ok=True)
            with patch.object(parser, "_request_with_proxy_fallback", side_effect=responses), \
                 patch("time.sleep"):
                result = parser._parse_single_file(pdf_path, out_dir, _retry_count=0, _force_ocr=None)
        self.assertTrue(result.get("success"))
        self.assertTrue(result.get("ocr_retried"))


if __name__ == "__main__":
    unittest.main()
