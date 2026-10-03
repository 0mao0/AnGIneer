"""空闲保温探针行为锁（10-03 生产空转复盘）：

v0.2.88 首版探针 doc_nodes=None → dense 整段跳过；查询词「知识库保温探针」
为索引外 token → FTS5 隐式 AND 全清零。日志"成功"实则零召回零页读。
本测试锁死三点：①节点必须装载并透传；②查询词不得含探针自描述毒词；
③默认查询用高频真实词、可经 ANGINEER_KEEPWARM_QUERY 覆盖。
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/aichat-api")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))

import importlib  # noqa: E402

_AICHAT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/aichat-api"))


def _load_main():
    """按归属加载 aichat-api 的 main：强制目录置顶 + 校验 __file__（同名包冲突防御）。"""
    while _AICHAT_DIR in sys.path:
        sys.path.remove(_AICHAT_DIR)
    sys.path.insert(0, _AICHAT_DIR)
    loaded = sys.modules.get("main")
    if loaded is not None:
        owner = os.path.abspath(getattr(loaded, "__file__", "") or "")
        if not owner.lower().startswith(_AICHAT_DIR.lower()):
            sys.modules.pop("main", None)
            loaded = None
    if loaded is None:
        loaded = importlib.import_module("main")
    return loaded


class _FakeTool:
    def __init__(self, record, result):
        self._record = record
        self._result = result

    def handler(self, query):
        self._record["query"] = query
        return self._result


class KeepwarmProbeTest(unittest.TestCase):
    def setUp(self):
        self.main = _load_main()

    def _run(self, *, nodes, result, env=None):
        record = {}

        def _fake_factory(**kwargs):
            record.update({k: v for k, v in kwargs.items() if k in ("doc_nodes", "library_id", "top_k")})
            return _FakeTool(record, result)

        env_patch = patch.dict(os.environ, env or {}, clear=False)
        with env_patch, patch("chat_agent._load_doc_nodes", return_value=nodes), patch(
            "angineer_core.agent_tools.RetrieverAdapter.knowledge_search", side_effect=_fake_factory
        ):
            items = self.main.run_keepwarm_probe()
        return items, record

    def test_empty_nodes_skips_without_search(self):
        """节点清单为空：返回 -1 且不构造检索工具（不得伪装成功）。"""
        calls = []
        with patch("chat_agent._load_doc_nodes", return_value=[]), patch(
            "angineer_core.agent_tools.RetrieverAdapter.knowledge_search",
            side_effect=lambda **kw: calls.append(kw),
        ):
            items = self.main.run_keepwarm_probe()
        self.assertEqual(items, -1)
        self.assertEqual(calls, [], "节点为空时不得构造检索工具")

    def test_nodes_loaded_and_passed_to_handler(self):
        """节点必须与真实请求同源装载并透传——v0.2.88 传 None 是 dense 空转根因。"""
        fake_nodes = [object()]
        items, record = self._run(nodes=fake_nodes, result={"items": [1, 2, 3]})
        self.assertEqual(items, 3)
        self.assertEqual(record["library_id"], "default")
        self.assertTrue(record["doc_nodes"], "doc_nodes 不得再传 None（DenseRetriever 对空节点直接 return []）")
        self.assertEqual(len(record["doc_nodes"]), 1)

    def test_default_query_has_no_poison_token_and_hits(self):
        """查询词不得含「保温探针」自描述毒词（FTS5 隐式 AND 整条清零的根因）；
        默认词应为启动预热同款高频字。"""
        _, record = self._run(nodes=[object()], result={"items": [1]})
        query = record["query"]
        self.assertNotIn("保温", query)
        self.assertNotIn("探针", query)
        self.assertEqual(query, "的 规范 设计")

    def test_query_env_override(self):
        _, record = self._run(
            nodes=[object()], result={"items": [1]}, env={"ANGINEER_KEEPWARM_QUERY": "混凝土 强度 等级"}
        )
        self.assertEqual(record["query"], "混凝土 强度 等级")


if __name__ == "__main__":
    unittest.main()
