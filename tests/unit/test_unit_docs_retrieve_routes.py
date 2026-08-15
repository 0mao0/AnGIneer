"""阶段 3b 测试：docs-api 内部检索端点——薄封装 retrieve_knowledge，scope 透传。"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-api")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/tree-core/src")))

import retrieve_routes  # noqa: E402


class RetrieveInternalRouteTests(unittest.TestCase):
    def test_endpoint_delegates_with_scope(self):
        with patch.object(retrieve_routes, "retrieve_knowledge") as mock_retrieve:
            mock_retrieve.return_value = {"items": [{"item_id": "a"}], "total": 1}
            request = retrieve_routes.RetrieveInternalRequest(
                query="测试",
                library_id="lib-x",
                doc_ids=["d1"],
                mode="text",
                task_type="content_qa",
                top_k=20,
            )
            result = retrieve_routes.retrieve_internal(request)

        self.assertEqual(result["total"], 1)
        kwargs = mock_retrieve.call_args.kwargs
        self.assertEqual(kwargs["query"], "测试")
        self.assertEqual(kwargs["library_id"], "lib-x")
        self.assertEqual(kwargs["doc_ids"], ["d1"])
        self.assertEqual(kwargs["mode"], "text")

    def test_endpoint_returns_error_payload_as_is(self):
        with patch.object(retrieve_routes, "retrieve_knowledge") as mock_retrieve:
            mock_retrieve.return_value = {"error": "检索全部失败"}
            request = retrieve_routes.RetrieveInternalRequest(query="测试")
            result = retrieve_routes.retrieve_internal(request)

        self.assertEqual(result["error"], "检索全部失败")


if __name__ == "__main__":
    unittest.main()
