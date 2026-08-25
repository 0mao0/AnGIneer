import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../scripts")))

from open_ragbench import download_dataset  # noqa: E402


class DownloadDatasetTests(unittest.TestCase):
    def _write_meta(self, directory: Path, queries_count: int = 3001):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "queries.json").write_text(
            json.dumps(
                {f"q{i}": {"query": "x", "type": "abstractive", "source": "text"} for i in range(queries_count)}
            ),
            encoding="utf-8",
        )
        (directory / "qrels.json").write_text(
            json.dumps({"q0": {"doc_id": "p1", "section_id": 0}}), encoding="utf-8"
        )
        (directory / "answers.json").write_text(json.dumps({"q0": "a"}), encoding="utf-8")
        (directory / "pdf_urls.json").write_text(
            json.dumps({"p1": "https://arxiv.org/pdf/1.pdf"}), encoding="utf-8"
        )

    def test_validate_meta_returns_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self._write_meta(directory)
            counts = download_dataset.validate_meta(directory)
            self.assertEqual(counts["queries"], 3001)
            self.assertEqual(counts["pdf_urls"], 1)

    def test_validate_meta_rejects_too_few_queries(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self._write_meta(directory, queries_count=10)
            with self.assertRaises(ValueError):
                download_dataset.validate_meta(directory)

    def test_hf_url(self):
        self.assertEqual(
            download_dataset.hf_url("pdf/arxiv/queries.json"),
            "https://hf-mirror.com/datasets/vectara/open_ragbench/resolve/main/pdf/arxiv/queries.json",
        )

    def test_looks_like_pdf_checks_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / "good.pdf"
            good.write_bytes(b"%PDF-1.4 content")
            bad = Path(tmp) / "bad.pdf"
            bad.write_bytes(b"not a pdf")
            self.assertTrue(download_dataset._looks_like_pdf(good))
            self.assertFalse(download_dataset._looks_like_pdf(bad))


if __name__ == "__main__":
    unittest.main()
