"""多库管理后端：注册表改组（set_group）+ 分组聚合（list_grouped_libraries）+ PATCH group_name。"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-core/src")))

from docs_core import library_registry  # noqa: E402


class SetGroupTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(delete=False)
        self._root = Path(self._tmp.name)
        self._patches = {
            "ANGINEER_REGISTRY_DB": str(self._root / "registry.sqlite"),
            "ANGINEER_DATA_ROOT": str(self._root),
        }
        self._old = {k: os.environ.get(k) for k in self._patches}
        os.environ.update(self._patches)

    def tearDown(self):
        for k, v in self._old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        # delete=False 的临时目录：注册表连接未显式 close 时 Windows 句柄占用，cleanup 会 PermissionError；
        # 用 weakref.finalize 接管删除，进程退出后句柄释放仍可清干净
        import shutil
        import weakref

        path = Path(self._tmp.name)
        self._tmp._finalizer.detach()
        weakref.finalize(self._tmp, shutil.rmtree, path, ignore_errors=True)

    def test_set_group_switches_collection_and_group_file(self):
        # 组文件已存在（flip 后）→ 改组即挂新组文件 + 新组 collection
        (self._root / "evals/groups").mkdir(parents=True)
        (self._root / "evals/groups/evals_corpus.sqlite").write_bytes(b"")
        library_registry.register_library("lib-a", name="A", group_name="standards")
        record = library_registry.set_group("lib-a", "evals")
        self.assertEqual(record.group_name, "evals")
        self.assertEqual(record.collection, "evals_corpus")
        self.assertEqual(record.sqlite_file, "evals/groups/evals_corpus.sqlite")

    def test_set_group_without_group_file_falls_back_to_default_file(self):
        library_registry.register_library("lib-b", name="B", group_name="standards")
        record = library_registry.set_group("lib-b", "evals")
        self.assertEqual(record.group_name, "evals")
        self.assertEqual(record.collection, "evals_corpus")
        self.assertEqual(record.sqlite_file, "knowledge/knowledge_index.sqlite")

    def test_set_group_rejects_unknown_group(self):
        library_registry.register_library("lib-c", name="C")
        with self.assertRaises(ValueError):
            library_registry.set_group("lib-c", "nope")

    def test_set_group_rejects_unregistered_library(self):
        with self.assertRaises(KeyError):
            library_registry.set_group("missing", "evals")

    def test_service_update_library_registers_unregistered_library(self):
        # 存量库从未进过注册表时，update_library 改组走补登记（KeyError 分支）
        from docs_core.docs_service import DocsService

        svc = DocsService()
        svc.create_library("lib-svc", "服务库")
        # 模拟「meta 有行、注册表无行」的存量态
        library_registry.set_status("lib-svc", library_registry.STATUS_RETIRED)
        import sqlite3

        db = library_registry.ensure_schema()
        with sqlite3.connect(db) as conn:
            conn.execute("DELETE FROM library_registry WHERE library_id='lib-svc'")
        library = svc.update_library("lib-svc", group_name="evals")
        self.assertEqual(library.group_name, "evals")
        record = library_registry.get_library("lib-svc")
        self.assertIsNotNone(record)
        self.assertEqual(record.group_name, "evals")


class GroupedLibrariesRouteTests(unittest.TestCase):
    """docs-api 路由面：/libraries/groups 聚合 + PATCH group_name 校验。"""

    def _client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from docs_routes import docs_router

        app = FastAPI()
        app.include_router(docs_router, prefix="/api/knowledge")
        return TestClient(app)

    def _service(self):
        from unittest.mock import MagicMock

        svc = MagicMock()
        svc.list_grouped_libraries.return_value = [
            {"group_name": "standards", "is_default_group": True, "known_group": True,
             "libraries": [{"id": "default", "name": "默认知识库", "doc_count": 3}]}
        ]
        return svc

    def test_groups_endpoint_returns_aggregation(self):
        sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-api")))
        from unittest.mock import patch

        with patch("docs_routes.get_docs_service", return_value=self._service()):
            body = self._client().get("/api/knowledge/libraries/groups")
        self.assertEqual(body.status_code, 200)
        data = body.json()
        self.assertEqual(data[0]["group_name"], "standards")
        self.assertEqual(data[0]["libraries"][0]["doc_count"], 3)

    def test_patch_rejects_unknown_group(self):
        sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-api")))
        from unittest.mock import patch

        svc = self._service()
        svc.update_library.side_effect = ValueError("未知库组: nope")
        with patch("docs_routes.get_docs_service", return_value=svc):
            resp = self._client().patch("/api/knowledge/libraries/lib-x", json={"group_name": "nope"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("未知库组", resp.json()["detail"])

    def test_patch_default_library_name_change_still_rejected(self):
        sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-api")))
        from unittest.mock import patch

        with patch("docs_routes.get_docs_service", return_value=self._service()):
            resp = self._client().patch("/api/knowledge/libraries/default", json={"name": "新名"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("改名", resp.json()["detail"])

    def test_patch_default_library_group_change_allowed(self):
        sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-api")))
        from unittest.mock import patch

        svc = self._service()
        svc.update_library.return_value = {"id": "default", "group_name": "evals"}
        with patch("docs_routes.get_docs_service", return_value=svc):
            resp = self._client().patch("/api/knowledge/libraries/default", json={"group_name": "evals"})
        self.assertEqual(resp.status_code, 200)
        svc.update_library.assert_called_once_with("default", name=None, description=None, group_name="evals")


if __name__ == "__main__":
    unittest.main()
