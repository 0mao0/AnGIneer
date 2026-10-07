"""DELETE /nodes 孤儿清理安全阀降级测试。

2026-10-07 实锤：批量删 38 个副本时每个响应都是 409，但节点其实已删除——
清理闸在主操作提交后拒绝，把「已删除成功」翻成假失败。降级版把 409 转为
响应告警字段；非 409 异常仍照抛（不以容错名义吞真实故障）。
"""
import os
import sys
import unittest
from unittest.mock import patch

from fastapi import HTTPException

_DOCS_API_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-api"))
sys.path.append(_DOCS_API_DIR)

import docs_routes  # noqa: E402


class _FakeNode:
    id = "v1-test"
    parse_task_id = None
    title = "测试节点"


class _FakeKs:
    def get_node(self, node_id):
        return _FakeNode()

    def delete_node(self, node_id):
        return True


def _guard_refuses(*args, **kwargs):
    raise HTTPException(status_code=409, detail={"message": "too many orphans", "count": 54, "limit": 20})


class DeleteNodeOrphanGuardTests(unittest.TestCase):
    def _patch_common(self):
        return [
            patch.object(docs_routes, "get_docs_service", return_value=_FakeKs()),
            patch.object(docs_routes, "cancel_parse_task_for_node", lambda *a: None),
            patch.object(docs_routes, "soft_delete_record", lambda *a: None),
            patch.object(docs_routes, "hard_delete_records_by_doc_id", lambda *a: None),
        ]

    def test_delete_survives_orphan_guard_refusal(self):
        patchers = self._patch_common() + [
            patch.object(docs_routes, "_clean_orphaned_records", _guard_refuses),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)
        res = docs_routes.delete_knowledge_node("v1-test")
        self.assertEqual(res["status"], "success")
        self.assertTrue(res["orphan_cleanup"]["deferred"])
        self.assertEqual(res["orphan_cleanup"]["pending"], 54)

    def test_delete_reports_cleaned_count_when_guard_passes(self):
        patchers = self._patch_common() + [
            patch.object(docs_routes, "_clean_orphaned_records", lambda ks: 3),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)
        res = docs_routes.delete_knowledge_node("v1-test")
        self.assertEqual(res["orphan_cleanup"], {"cleaned": 3})

    def test_non_guard_error_still_propagates(self):
        def boom(*args, **kwargs):
            raise HTTPException(status_code=500, detail="db broken")

        patchers = self._patch_common() + [
            patch.object(docs_routes, "_clean_orphaned_records", boom),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)
        with self.assertRaises(HTTPException) as ctx:
            docs_routes.delete_knowledge_node("v1-test")
        self.assertEqual(ctx.exception.status_code, 500)

    def test_force_delete_survives_orphan_guard_refusal(self):
        patchers = self._patch_common() + [
            patch.object(docs_routes, "_clean_orphaned_records", _guard_refuses),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)
        res = docs_routes.force_delete_knowledge_node("v1-test")
        self.assertEqual(res["status"], "success")
        self.assertTrue(res["orphan_cleanup"]["deferred"])


if __name__ == "__main__":
    unittest.main()
