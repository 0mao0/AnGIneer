import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../scripts")))

from open_ragbench import common  # noqa: E402


class OpenRagBenchCommonTests(unittest.TestCase):
    def test_hf_files_covers_four_metadata_files(self):
        self.assertEqual(
            set(common.HF_FILES),
            {"pdf_urls.json", "queries.json", "answers.json", "qrels.json"},
        )

    def test_repo_root_points_to_project(self):
        self.assertTrue((common.REPO_ROOT / "services").is_dir())

    def test_endpoints_build_expected_urls(self):
        ep = common.Endpoints("http://localhost:8790", "http://localhost:8791")
        self.assertEqual(ep.login, "http://localhost:8790/api/v1/auth/login")
        self.assertEqual(ep.parse, "http://localhost:8790/api/v1/documents/parse")
        self.assertEqual(
            ep.status("d1"),
            "http://localhost:8790/api/v1/documents/d1/status",
        )
        self.assertEqual(ep.eval_runs, "http://localhost:8791/api/evals/runs")


if __name__ == "__main__":
    unittest.main()
