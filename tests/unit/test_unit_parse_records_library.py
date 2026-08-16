"""解析记录按 library_id 过滤。"""
import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "services" / "docs-api"))


class ParseRecordsLibraryFilterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["PARSE_RECORDS_DB_PATH"] = str(Path(self.tmp.name) / "parse_records.sqlite")
        self.mod = importlib.import_module("models.parse_record")
        importlib.reload(self.mod)
        self.mod.init_db()
        self.mod.insert_record(self.mod.ParseRecord(doc_id="d1", task_id="t-default", uploaded_by="u1", library_id="default"))
        self.mod.insert_record(self.mod.ParseRecord(doc_id="d2", task_id="t-lib-a", uploaded_by="u1", library_id="lib-a"))

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("PARSE_RECORDS_DB_PATH", None)

    def test_list_records_filters_by_library(self):
        default = self.mod.list_records(library_id="default")
        lib_a = self.mod.list_records(library_id="lib-a")
        all_records = self.mod.list_records()
        self.assertEqual([r["task_id"] for r in default], ["t-default"])
        self.assertEqual([r["task_id"] for r in lib_a], ["t-lib-a"])
        self.assertEqual(len(all_records), 2)


if __name__ == "__main__":
    unittest.main()
