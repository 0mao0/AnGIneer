"""Phase D4 测试：赌博式预检与路由的 library_ids 穿透 + memo 键一致性（上批评审跟进项）。

覆盖：
1. fire_speculative_first_search 把集合透传给 RetrieverAdapter.knowledge_search（多库）；
   B1（2026-10-04 质量评审）：单元素集合与缺省一律收敛 None——agent_tools 对 truthy 集合
   给结果挂 scope 键，主路单库传 None 不挂，预检若带 ["lib"] 则单库 tool 观测 shape
   取决于预检竞态是否命中，破「旧 body 逐位不变」。
2. 预检 kwargs 与主路（agent_policy.build_attempts → build_qa_config → knowledge_search）
   kwargs 构出的 agent_tools._search_memo_key 相等——多库/单库各钉一例；单库另跑真实
   _run_knowledge_search 双调用证明 memo 复用（_prefetch_ms 上浮）且结果不带 scope。
3. route_request 生成的 ScopeContext 携带集合（library_ids），旧调用形状不变。
"""
import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

_SERVICES = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services"))
sys.path.append(os.path.join(_SERVICES, "aichat-api"))
for _pkg in ("angineer-core", "ai-inference", "docs-core"):
    sys.path.insert(0, os.path.join(_SERVICES, _pkg, "src"))

import route_pre  # noqa: E402
from angineer_core import agent_policy, agent_tools  # noqa: E402
from angineer_core.agent_tools import _run_knowledge_search, _search_memo_key  # noqa: E402


class _RecordingTool:
    def __init__(self, sink):
        self._sink = sink

    def handler(self, query=None, **kwargs):
        self._sink["handler_query"] = query
        return {"items": []}


def _capture_fire_kwargs(query, library_id, doc_ids, library_ids=None):
    """跑一次 fire（daemon 线程）捕获预检侧 knowledge_search kwargs。"""
    seen = {}
    mock_adapter = MagicMock()

    def _knowledge_search(**kw):
        seen["kw"] = kw
        return _RecordingTool(seen)

    mock_adapter.knowledge_search.side_effect = _knowledge_search
    with patch("angineer_core.agent_tools.route_parallel_enabled", return_value=True), \
         patch("angineer_core.agent_tools.RetrieverAdapter", mock_adapter), \
         patch("docs_core.step09_query.agent_port.looks_like_table_query", return_value=False):
        route_pre.fire_speculative_first_search(
            query, library_id, doc_ids,
            load_nodes=lambda: [], has_history=False,
            library_ids=library_ids,
        )
    deadline = time.time() + 3.0
    while "kw" not in seen and time.time() < deadline:
        time.sleep(0.05)
    return seen["kw"], seen


class _CaptureClient:
    """注入 retrieval_client 的假客户端（同 tests/angineer-core/test_search_memo.py 口径）。"""

    def retrieve(self, **kwargs):
        return [], {}


class SpeculativeLibraryIdsTests(unittest.TestCase):
    def test_speculative_tool_receives_library_ids(self):
        query = "混凝土抗压强度试验方法"
        kw, seen = _capture_fire_kwargs(query, None, [], library_ids=["libA", "libB"])
        self.assertEqual(kw.get("library_ids"), ["libA", "libB"])
        # handler 被真实调用（memo 复用前提：预检真的跑了一次检索）
        self.assertEqual(seen.get("handler_query"), query)

    def test_speculative_single_library_collapses_to_none(self):
        """B1 翻转钉：单库（不传集合 / 单元素集合）都必须收敛 None——
        与主路单库（build_attempts library_ids=None）逐位同形，结果不挂 scope 键。"""
        query = "混凝土抗压强度试验方法"
        kw_legacy, _ = _capture_fire_kwargs(query, "libA", [])
        self.assertIsNone(kw_legacy.get("library_ids"))
        kw_single, _ = _capture_fire_kwargs(query, "libA", [], library_ids=["libA"])
        self.assertIsNone(kw_single.get("library_ids"))


class SpeculativeMemoKeyConsistencyTests(unittest.TestCase):
    """预检 kwargs 与主路 kwargs 构出的 memo 键必须相等（route_pre docstring 契约）。"""

    QUERY_MULTI = "混凝土抗压强度怎么评定（多库钉）"
    QUERY_SINGLE = "混凝土抗压强度怎么评定（单库钉）"
    LIBS = ["libA", "libB"]

    def _main_path_kwargs(self, library_ids, library_id=None):
        """主路 = agent_policy.build_attempts（L1 档）→ config_factory() → build_qa_config。"""
        captured = {}
        mock_adapter = MagicMock()

        def _knowledge_search(**kw):
            captured["kw"] = kw
            return MagicMock()

        mock_adapter.knowledge_search.side_effect = _knowledge_search
        import angineer_core.agent_configs as agent_configs

        with patch.object(agent_configs, "RetrieverAdapter", mock_adapter):
            attempts = agent_policy.build_attempts(
                intent_result=None, scene="qa",
                library_id=library_id or self.LIBS[0], doc_ids=[],
                load_nodes=lambda: [], llm_factory=lambda: object(),
                library_ids=library_ids,
            )
            attempts[0].config_factory()
        return captured["kw"]

    @staticmethod
    def _as_handler_kwargs(kw, query):
        """模拟 knowledge_search handler 的最终入参（query/prefix 由 handler 合并）。"""
        merged = dict(kw)
        merged.update(query=query, prefix="K", marker_allocator=None,
                      doc_nodes=[], retrieval_client=None)
        return merged

    def test_memo_key_speculative_matches_main_path_multi(self):
        spec_kw, _ = _capture_fire_kwargs(self.QUERY_MULTI, self.LIBS[0], [],
                                          library_ids=list(self.LIBS))
        main_kw = self._main_path_kwargs(list(self.LIBS))
        with patch("angineer_core.agent_tools.route_parallel_enabled", return_value=True):
            key_spec = _search_memo_key(self._as_handler_kwargs(spec_kw, self.QUERY_MULTI))
            key_main = _search_memo_key(self._as_handler_kwargs(main_kw, self.QUERY_MULTI))
        self.assertIsNotNone(key_spec)
        self.assertEqual(key_spec, key_main)

    def test_memo_key_differs_when_library_set_differs(self):
        """负对照：集合不同必须不同键（防「去 scope 后同键串桶」的假绿）。"""
        spec_kw, _ = _capture_fire_kwargs(self.QUERY_MULTI, self.LIBS[0], [],
                                          library_ids=list(self.LIBS))
        main_kw = self._main_path_kwargs(["libA", "libC"])  # 与预检集合不同
        with patch("angineer_core.agent_tools.route_parallel_enabled", return_value=True):
            self.assertNotEqual(
                _search_memo_key(self._as_handler_kwargs(spec_kw, self.QUERY_MULTI)),
                _search_memo_key(self._as_handler_kwargs(main_kw, self.QUERY_MULTI)),
            )

    def test_single_library_spec_matches_main_and_result_has_no_scope(self):
        """B1 主钉（单库）：spec kwargs（端点透传 ["libA"]）与主路 kwargs（None）构出的
        memo 键相等；真实 _run_knowledge_search 双调用证明 memo 单发复用（_prefetch_ms
        上浮）且两侧结果均不带 scope 键——单库观测 shape 与预检竞态无关。"""
        spec_kw, _ = _capture_fire_kwargs(self.QUERY_SINGLE, "libA", [], library_ids=["libA"])
        main_kw = self._main_path_kwargs(None, library_id="libA")
        self.assertIsNone(spec_kw.get("library_ids"))
        self.assertIsNone(main_kw.get("library_ids"))

        client = _CaptureClient()
        spec_call = self._as_handler_kwargs(spec_kw, self.QUERY_SINGLE)
        spec_call["retrieval_client"] = client
        main_call = self._as_handler_kwargs(main_kw, self.QUERY_SINGLE)
        main_call["retrieval_client"] = client
        with agent_tools._SEARCH_MEMO_LOCK:
            agent_tools._SEARCH_MEMO.clear()
        try:
            with patch("angineer_core.agent_tools.route_parallel_enabled", return_value=True):
                self.assertEqual(_search_memo_key(spec_call), _search_memo_key(main_call))
                res_spec = _run_knowledge_search(**spec_call, _from_speculative=True)
                res_main = _run_knowledge_search(**main_call)
        finally:
            with agent_tools._SEARCH_MEMO_LOCK:
                agent_tools._SEARCH_MEMO.clear()
        self.assertIsInstance(res_spec, dict)
        self.assertNotIn("scope", res_spec)
        self.assertNotIn("scope", res_main)
        # 主路命中预检成品（键对齐的直接证据）：_prefetch_ms 由 memo 命中分支上浮
        self.assertIn("_prefetch_ms", res_main)
        self.assertEqual(
            {k: v for k, v in res_spec.items() if not k.startswith("_")},
            {k: v for k, v in res_main.items() if not k.startswith("_")},
        )


class RouteRequestScopeTests(unittest.IsolatedAsyncioTestCase):
    async def _classify(self, query, config_name, mode):
        return None  # fallback 决策即可，本用例只钉 scope

    async def test_scope_carries_library_ids(self):
        decision = await route_pre.route_request(
            query="q", scene="qa", library_id="libA", doc_ids=["d1"],
            config_name=None, mode="instruct", classify=self._classify,
            library_ids=["libA", "libB"],
        )
        self.assertEqual(decision.scope.library_ids, ["libA", "libB"])
        self.assertEqual(decision.scope.library_id, "libA")  # D8：首项=主库
        self.assertEqual(decision.scope.doc_ids, ["d1"])

    async def test_scope_legacy_shape_without_library_ids(self):
        decision = await route_pre.route_request(
            query="q", scene="qa", library_id="libA", doc_ids=[],
            config_name=None, mode="instruct", classify=self._classify,
        )
        self.assertEqual(decision.scope.library_ids, ["libA"])
        self.assertEqual(decision.scope.library_id, "libA")


if __name__ == "__main__":
    unittest.main()
