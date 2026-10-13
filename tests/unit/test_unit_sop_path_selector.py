"""path_selector 合成管线单元测试（docs-api HTTP 全 mock，LLM 断网走骨架兜底）。"""
import os, sys, unittest
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/sop-api")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/sop-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))

from unittest.mock import MagicMock, patch
from path_selector import SynthUnavailable, extract_keywords, build_candidate_paths, synthesize_sop


def _resp(payload):
    r = MagicMock(); r.json.return_value = payload; r.raise_for_status.return_value = None; return r


class TestExtractKeywords(unittest.TestCase):
    def test_cjk_and_ascii_tokens(self):
        kw = extract_keywords("杂货船DWT40000的设计船型满载吃水怎么算？")
        self.assertIn("杂货船", "".join(kw))
        self.assertTrue(len(kw) <= 6)

    def test_empty_query_raises_later(self):
        self.assertEqual(extract_keywords("？！。 "), [])


class TestBuildCandidatePaths(unittest.TestCase):
    def test_action_anchored_incoming_chain(self):
        entities = [
            {"entity_id": "e1", "name": "设计吃水", "layer": "action"},
            {"entity_id": "e2", "name": "吨级", "layer": "concept"},
        ]
        rels = {"e1": [{"relation_id": "r1", "source_id": "e2", "target_id": "e1",
                        "library_id": "lib", "doc_id": "doc"}]}
        paths = build_candidate_paths(entities, rels, library_id="lib", doc_id="doc")
        self.assertTrue(any(p == ["吨级", "设计吃水"] for p in paths))


class TestSynthesizeSop(unittest.TestCase):
    def test_no_candidates_raises_unavailable(self):
        session = MagicMock()
        session.get.return_value = _resp([])
        with patch("path_selector.extract_keywords", return_value=["吃水"]):
            with self.assertRaises(SynthUnavailable):
                synthesize_sop("随便", "lib", [], session=session, base_url="http://x", llm_enabled=False)

    def test_success_returns_sop_dict(self):
        session = MagicMock()
        # 实际只 2 次 GET：关键词搜索 + 锚点 e1 的关系；e2 不在实体集内，入向链止于锚点
        session.get.side_effect = [
            _resp([{"entity_id": "e1", "name": "设计吃水", "layer": "action", "status": "approved"}]),
            _resp([{"relation_id": "r1", "source_id": "e2", "target_id": "e1",
                    "library_id": "lib", "doc_id": "doc"}]),
        ]
        with patch("path_selector.extract_keywords", return_value=["吃水"]), \
             patch("path_selector._llm_generate", return_value=None):  # 断网→骨架兜底
            result = synthesize_sop("杂货船设计吃水", "lib", [], session=session, base_url="http://x", llm_enabled=True)
        self.assertIn("sop", result)
        self.assertTrue(result["sop"]["steps"])


if __name__ == "__main__":
    unittest.main()
