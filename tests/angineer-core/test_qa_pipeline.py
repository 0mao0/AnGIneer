"""qa_pipeline 兼容层单测：仅保留 REFUSAL_ANSWER_TEXT re-export。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))

from angineer_core.agent_messages import REFUSAL_ANSWER_TEXT as SOURCE  # noqa: E402
from angineer_core.qa_pipeline import REFUSAL_ANSWER_TEXT  # noqa: E402


class QaPipelineReexportTests(unittest.TestCase):
    def test_refusal_text_reexported(self):
        self.assertEqual(REFUSAL_ANSWER_TEXT, SOURCE)
        self.assertIn("没有检索到足够证据支持最终结论", REFUSAL_ANSWER_TEXT)


if __name__ == "__main__":
    unittest.main()
