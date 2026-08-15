"""阶段 3b 测试：angineer-core Docs 检索 HTTP client 与 agent_tools 接线（env 未配置回退本地）。"""
import os
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/ai-inference/src")))

from angineer_core.agent_tools import RetrieverAdapter  # noqa: E402
from angineer_core.docs_retrieval_client import DocsRetrievalClient, client_from_env  # noqa: E402


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def _item_payload(item_id="a", doc_id="d1", text="正文证据"):
    return {
        "item_id": item_id,
        "entity_type": "chunk",
        "doc_id": doc_id,
        "title": "条文",
        "text": text,
        "score": 0.9,
        "rerank_score": None,
        "citation_target_id": None,
        "retrieval_policy": None,
        "metadata": {"doc_title": "规范A"},
    }


class DocsRetrievalClientTests(unittest.TestCase):
    def test_retrieve_posts_and_rebuilds_items(self):
        client = DocsRetrievalClient("http://docs-api:8010/")
        with patch("angineer_core.docs_retrieval_client.requests.post") as mock_post:
            mock_post.return_value = _FakeResponse({"items": [_item_payload()], "total": 1})
            items = client.retrieve(
                mode="text", query="测试", library_id="lib-x", doc_ids=["d1"],
            )

        (url,), kwargs = mock_post.call_args
        self.assertEqual(url, "http://docs-api:8010/api/knowledge/internal/retrieve")
        self.assertEqual(kwargs["json"]["library_id"], "lib-x")
        self.assertEqual(kwargs["json"]["doc_ids"], ["d1"])
        self.assertEqual(kwargs["json"]["mode"], "text")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].item_id, "a")
        self.assertEqual(items[0].metadata["doc_title"], "规范A")

    def test_retrieve_raises_on_error_payload(self):
        client = DocsRetrievalClient("http://docs-api:8010")
        with patch("angineer_core.docs_retrieval_client.requests.post") as mock_post:
            mock_post.return_value = _FakeResponse({"error": "检索全部失败"})
            with self.assertRaises(RuntimeError):
                client.retrieve(mode="text", query="q", library_id="default")

    def test_client_from_env_disabled_without_url(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ANGINEER_DOCS_API_URL", None)
            self.assertIsNone(client_from_env())

    def test_client_from_env_enabled_with_url(self):
        with patch.dict(os.environ, {"ANGINEER_DOCS_API_URL": "http://docs-api:8010"}):
            client = client_from_env()
        self.assertIsNotNone(client)
        self.assertEqual(client.base_url, "http://docs-api:8010")


class KnowledgeSearchClientWiringTests(unittest.TestCase):
    def test_knowledge_search_uses_injected_client(self):
        from docs_core.step09_query.protocols.contracts import RetrievedItem

        client = Mock()
        client.retrieve.return_value = [
            RetrievedItem(
                item_id="a", entity_type="chunk", doc_id="d1",
                title="条文", text="正文证据", score=0.9,
                metadata={"doc_title": "规范A"},
            )
        ]

        tool = RetrieverAdapter.knowledge_search(library_id="lib-x", retrieval_client=client)
        result = tool.handler(query="测试")

        self.assertEqual(result["items"][0]["item_id"], "a")
        self.assertEqual(result["evidences"][0]["evidence_id"], "a")
        self.assertEqual(result["evidences"][0]["library_id"], "lib-x")
        self.assertIn("《规范A》", result["items"][0]["text"])
        client.retrieve.assert_called_once()
        self.assertEqual(client.retrieve.call_args.kwargs["mode"], "text")

    def test_knowledge_search_falls_back_to_local_on_client_failure(self):
        client = Mock()
        client.retrieve.side_effect = RuntimeError("connection refused")

        class _FakeRetriever:
            def __init__(self, items):
                self._items = items

            def retrieve(self, *args, **kwargs):
                return list(self._items)

        from docs_core.step09_query.protocols.contracts import RetrievedItem

        local_item = RetrievedItem(
            item_id="local1", entity_type="chunk", doc_id="d1",
            title="条文", text="本地证据", score=0.8, metadata={},
        )
        tool = RetrieverAdapter.knowledge_search(
            library_id="lib-x",
            dense=_FakeRetriever([local_item]),
            sparse=_FakeRetriever([]),
            clause=_FakeRetriever([]),
            retrieval_client=client,
        )
        result = tool.handler(query="测试")

        self.assertEqual(result["items"][0]["item_id"], "local1")

    def test_table_search_uses_injected_client(self):
        from docs_core.step09_query.protocols.contracts import RetrievedItem

        client = Mock()
        client.retrieve.return_value = [
            RetrievedItem(
                item_id="t1", entity_type="table", doc_id="d1",
                title="表", text="表格内容", score=0.7, metadata={},
            )
        ]

        tool = RetrieverAdapter.table_search(library_id="lib-x", retrieval_client=client)
        result = tool.handler(query="表格")

        self.assertEqual(result["items"][0]["item_id"], "t1")
        self.assertEqual(result["evidences"][0]["kind"], "table")
        self.assertEqual(client.retrieve.call_args.kwargs["mode"], "table")


if __name__ == "__main__":
    unittest.main()
