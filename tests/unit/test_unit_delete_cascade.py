"""回归测试：删除路径级联收敛——force 删除硬删记录、删除后自动清理孤儿记录。"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-api")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/tree-core/src")))

import docs_routes  # noqa: E402
import models.parse_record as parse_record  # noqa: E402


class DeleteCascadeTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmp_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp_dir, ignore_errors=True))

    def _use_tmp_db(self):
        db_path = os.path.join(self.tmp_dir, "parse_records.sqlite")
        return patch.object(parse_record, "DB_PATH", db_path)

    def test_force_delete_hard_deletes_records(self):
        node = type("N", (), {"parse_task_id": None, "title": "t"})()
        with self._use_tmp_db():
            parse_record.insert_record(parse_record.ParseRecord(doc_id="d-force", task_id="t1"))
            with patch.object(docs_routes, "get_docs_service") as mock_ks, \
                 patch.object(docs_routes, "clean_orphaned_records", return_value=None):
                mock_ks.return_value.get_node.return_value = node
                mock_ks.return_value.delete_node.return_value = True
                docs_routes.force_delete_knowledge_node("d-force")
            rows = [r for r in parse_record.list_records() if r.get("doc_id") == "d-force"]

        self.assertEqual(rows, [])

    def test_normal_delete_soft_deletes_records(self):
        node = type("N", (), {"parse_task_id": None, "title": "t"})()
        with self._use_tmp_db():
            parse_record.insert_record(parse_record.ParseRecord(doc_id="d-soft", task_id="t1"))
            with patch.object(docs_routes, "get_docs_service") as mock_ks, \
                 patch.object(docs_routes, "cancel_parse_task_for_node"), \
                 patch.object(docs_routes, "clean_orphaned_records", return_value=None):
                mock_ks.return_value.get_node.return_value = node
                mock_ks.return_value.delete_node.return_value = True
                docs_routes.delete_knowledge_node("d-soft")
            rows = [r for r in parse_record.list_records() if r.get("doc_id") == "d-soft"]

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "deleted")

    def test_delete_triggers_orphan_cleanup(self):
        node = type("N", (), {"parse_task_id": None, "title": "t"})()
        with self._use_tmp_db():
            with patch.object(docs_routes, "get_docs_service") as mock_ks, \
                 patch.object(docs_routes, "cancel_parse_task_for_node"), \
                 patch.object(docs_routes, "_clean_orphaned_records") as mock_clean:
                mock_ks.return_value.get_node.return_value = node
                mock_ks.return_value.delete_node.return_value = True
                docs_routes.delete_knowledge_node("d-x")

        mock_clean.assert_called_once()

    def test_soft_delete_folder_cascades_records(self):
        """软删除文件夹时，子树内全部文档的解析记录级联标记为 deleted（列表显示“用户已删”）。"""
        node = type("N", (), {"parse_task_id": None, "title": "folder"})()
        with self._use_tmp_db():
            parse_record.insert_record(parse_record.ParseRecord(doc_id="doc-a", task_id="t1"))
            parse_record.insert_record(parse_record.ParseRecord(doc_id="doc-b", task_id="t2"))
            with patch.object(docs_routes, "get_docs_service") as mock_ks, \
                 patch.object(docs_routes, "cancel_parse_task_for_node"), \
                 patch.object(docs_routes, "soft_delete_record", wraps=parse_record.soft_delete_record) as soft_mock:
                ks = mock_ks.return_value
                ks.get_node.return_value = node
                ks.soft_delete_node.return_value = True
                ks.get_subtree_document_ids.return_value = ["doc-a", "doc-b"]
                docs_routes.soft_delete_knowledge_node("folder-1")

            rows = [r for r in parse_record.list_records() if r.get("doc_id") in ("doc-a", "doc-b")]

        self.assertEqual(sorted(r["status"] for r in rows), ["deleted", "deleted"])
        soft_mock.assert_any_call("folder-1")
        soft_mock.assert_any_call("doc-a")
        soft_mock.assert_any_call("doc-b")


if __name__ == "__main__":
    unittest.main()
