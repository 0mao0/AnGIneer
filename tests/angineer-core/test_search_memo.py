"""检索 memo 单测（需求 §5.2 基础并行的复用机制，ANGINEER_ROUTE_PARALLEL 总闸）。

覆盖：单发复用（命中即弹出）、参数不同不误命中、开关关闭直穿、错误结果不入缓存、
键随 prefix（K/E）区分。fake retrieval_client 计数 retrieve() 调用次数。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/ai-inference/src")))

from angineer_core import agent_tools  # noqa: E402
from angineer_core.agent_tools import _run_knowledge_search  # noqa: E402


class CountingClient:
    def __init__(self):
        self.calls = 0

    def retrieve(self, **kwargs):
        self.calls += 1
        return []


def base_kwargs(client, **overrides):
    kw = {
        "query": "什么是设计低水位？",
        "library_id": "lib-x",
        "doc_ids": ["d1"],
        "doc_nodes": [],
        "top_k": 20,
        "task_type": "content_qa",
        "filters": None,
        "prefix": "K",
        "marker_allocator": None,
        "rerank": True,
        "retrieval_client": client,
        "config_name": None,
        "mode": "instruct",
    }
    kw.update(overrides)
    return kw


class SearchMemoTests(unittest.TestCase):
    def setUp(self):
        self._old = os.environ.get("ANGINEER_ROUTE_PARALLEL")
        os.environ["ANGINEER_ROUTE_PARALLEL"] = "true"
        with agent_tools._SEARCH_MEMO_LOCK:
            agent_tools._SEARCH_MEMO.clear()

    def tearDown(self):
        if self._old is None:
            os.environ.pop("ANGINEER_ROUTE_PARALLEL", None)
        else:
            os.environ["ANGINEER_ROUTE_PARALLEL"] = self._old
        with agent_tools._SEARCH_MEMO_LOCK:
            agent_tools._SEARCH_MEMO.clear()

    def test_second_identical_call_hits_memo_single_use(self):
        client = CountingClient()
        r1 = _run_knowledge_search(**base_kwargs(client))
        r2 = _run_knowledge_search(**base_kwargs(client))
        self.assertEqual(client.calls, 1)
        self.assertIs(r2, r1)  # 单发复用：命中即弹出
        r3 = _run_knowledge_search(**base_kwargs(client))
        self.assertEqual(client.calls, 2)  # 弹出后第三次是真检索
        self.assertIsNot(r3, r1)

    def test_different_params_miss(self):
        client = CountingClient()
        _run_knowledge_search(**base_kwargs(client))
        _run_knowledge_search(**base_kwargs(client, top_k=5))
        _run_knowledge_search(**base_kwargs(client, library_id="lib-y"))
        _run_knowledge_search(**base_kwargs(client, prefix="E"))
        self.assertEqual(client.calls, 4)

    def test_switch_off_passes_through(self):
        os.environ["ANGINEER_ROUTE_PARALLEL"] = "false"
        client = CountingClient()
        _run_knowledge_search(**base_kwargs(client))
        _run_knowledge_search(**base_kwargs(client))
        self.assertEqual(client.calls, 2)

    def test_error_result_not_stored(self):
        class FailingClient:
            def __init__(self):
                self.calls = 0

            def retrieve(self, **kwargs):
                self.calls += 1
                raise RuntimeError("docs-api down")

        client = FailingClient()
        _run_knowledge_search(**base_kwargs(client))
        _run_knowledge_search(**base_kwargs(client))
        self.assertEqual(client.calls, 2)  # 错误结果不入缓存，第二次仍真检索


if __name__ == "__main__":
    unittest.main()
