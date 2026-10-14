"""path_selector 合成管线单元测试（docs-api HTTP 全 mock，LLM 断网走骨架兜底）。"""
import os, sys, unittest
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/sop-api")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/sop-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))

from unittest.mock import MagicMock, patch
from path_selector import (SynthUnavailable, extract_keywords, build_candidate_paths,
                           satisfy_required_closure, synthesize_sop)


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


class TestSatisfyRequiredClosure(unittest.TestCase):
    """required 引用闭包补齐（2026-10-14 手测实踩：LLM 产出声明 required 但步骤未引用 → 校验全 412）。"""

    def _sop(self, required, steps):
        return {"blackboard": {"required": required, "outputs": []}, "steps": steps}

    def test_existing_key_gets_ref_appended(self):
        sop = self._sop(["排水量"], [{"id": "s1", "inputs": {"排水量": "满载排水量"}, "outputs": {"x": "y"}}])
        satisfy_required_closure(sop)
        self.assertIn("${排水量}", sop["steps"][0]["inputs"]["排水量"])

    def test_absent_key_injected_into_first_step(self):
        sop = self._sop(["船宽"], [{"id": "s1", "inputs": {}, "outputs": {}},
                                   {"id": "s2", "inputs": {"其他": "说明"}, "outputs": {}}])
        satisfy_required_closure(sop)
        self.assertIn("${船宽}", sop["steps"][0]["inputs"]["船宽"])
        self.assertEqual(sop["steps"][1]["inputs"], {"其他": "说明"})  # 不越位乱插

    def test_already_referenced_and_produced_untouched(self):
        sop = self._sop(["A", "B", "user_query"], [
            {"id": "s1", "inputs": {"x": "取自${A}"}, "outputs": {"B": "产出B"}}])
        before = repr(sop)
        satisfy_required_closure(sop)
        self.assertEqual(repr(sop), before)  # 幂等：已满足的键不动

    def test_no_steps_or_required_is_noop(self):
        for sop in (self._sop([], [{"id": "s1", "inputs": {}, "outputs": {}}]),
                    self._sop(["X"], [])):
            before = repr(sop)
            satisfy_required_closure(sop)
            self.assertEqual(repr(sop), before)


if __name__ == "__main__":
    unittest.main()
