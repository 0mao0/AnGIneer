"""P2-3 v2 导入 CLI 参数契约（薄壳，不重复测 apply_import）。"""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../scripts")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-core/src")))

import kb_corpus_import as cli  # noqa: E402


class ImportCliTests(unittest.TestCase):
    def _run(self, argv, result=None):
        captured = {}

        def fake_apply(package, **kwargs):
            captured["package"] = package
            captured.update(kwargs)
            return result or {"mode": "dry-run", "libraries": []}

        with mock.patch.object(cli, "apply_import", side_effect=fake_apply), \
             mock.patch.object(cli, "resolve_data_root", return_value=Path("data")):
            rc = cli.main(argv)
        return rc, captured

    def test_default_is_dry_run_and_passes_group_and_no_vectors(self):
        rc, captured = self._run([
            "--package", "p.zip", "--group", "evals", "--no-vectors",
        ])
        self.assertEqual(rc, 0)
        self.assertFalse(captured["apply"])
        self.assertFalse(captured["with_vectors"])
        self.assertEqual(captured["group_name"], "evals")
        self.assertIsNone(captured["libraries"])

    def test_only_splits_ids_and_apply(self):
        rc, captured = self._run([
            "--package", "p.zip", "--only", "lib-a, lib-b", "--apply",
        ], result={"mode": "applied", "libraries": ["lib-a", "lib-b"]})
        self.assertEqual(rc, 0)
        self.assertTrue(captured["apply"])
        self.assertEqual(captured["libraries"], ["lib-a", "lib-b"])

    def test_bundle_error_returns_nonzero(self):
        with mock.patch.object(cli, "apply_import", side_effect=cli.BundleError("坏包")), \
             mock.patch.object(cli, "resolve_data_root", return_value=Path("data")):
            self.assertEqual(cli.main(["--package", "p.zip"]), 1)


if __name__ == "__main__":
    unittest.main()
