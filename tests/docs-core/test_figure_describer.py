"""figure_describe 阶段单测：图块筛选、jsonl 写回、容错、阶段注册与 legacy 状态兼容。"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "services" / "docs-core" / "src"))

from docs_core.step04_structure.figure_describer import (  # noqa: E402
    describe_figures_in_graph,
    is_enabled,
    vlm_config,
)
from docs_core.parse_pipeline import (  # noqa: E402
    STAGE_KIND_SOFT,
    STAGE_REGISTRY,
    _PIPELINE_ORDER,
    derive_overall_status,
    resolve_stage_order,
)
from docs_core.step05_sqlite_fts.rebuild.canonical_builder import (  # noqa: E402
    build_canonical_blocks_from_source,
)


def _write_graph(graph_dir: Path, nodes):
    graph_dir.mkdir(parents=True, exist_ok=True)
    graph_path = graph_dir / "doc_blocks_graph.jsonl"
    graph_path.write_text(
        "\n".join(json.dumps(n, ensure_ascii=False) for n in nodes) + "\n",
        encoding="utf-8",
    )
    return graph_path


def _env(**kwargs):
    return patch.dict(os.environ, kwargs, clear=False)


class FigureDescriberConfigTests(unittest.TestCase):
    def test_is_enabled_default_true(self):
        with _env():
            os.environ.pop("FIGURE_DESCRIBE_ENABLED", None)
            self.assertTrue(is_enabled())

    def test_is_enabled_disabled(self):
        with _env(FIGURE_DESCRIBE_ENABLED="0"):
            self.assertFalse(is_enabled())

    def test_vlm_config_falls_back_to_chat_key(self):
        with _env(FIGURE_DESCRIBE_VLM_API_KEY="", ANGINEER_CHAT_API_KEY="chat-key"):
            self.assertEqual(vlm_config()["api_key"], "chat-key")
        with _env(FIGURE_DESCRIBE_VLM_API_KEY="fig-key", ANGINEER_CHAT_API_KEY=""):
            self.assertEqual(vlm_config()["api_key"], "fig-key")
        self.assertEqual(vlm_config()["model"], "Qwen3.6-35B-A3B-FP8")


class FigureDescriberPipelineTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.env = _env(KNOWLEDGE_BASE_DIR=str(self.base))
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self._tmp.cleanup()

    def _graph_dir(self):
        return self.base / "libraries" / "lib-t" / "documents" / "doc-1" / "parsed"

    def test_describe_writes_back_and_skips_existing(self):
        graph_dir = self._graph_dir()
        (graph_dir / "images").mkdir(parents=True, exist_ok=True)
        (graph_dir / "images" / "a.jpg").write_bytes(b"fake")
        nodes = [
            {"block_uid": "f1", "block_type": "image", "image_path": "images/a.jpg",
             "figure_description": "已有描述"},
            {"block_uid": "f2", "block_type": "image", "image_path": "images/a.jpg"},
            {"block_uid": "p1", "block_type": "text"},
        ]
        _write_graph(graph_dir, nodes)

        with patch("docs_core.step04_structure.figure_describer.describe_image",
                   return_value="新描述") as mock_desc:
            stats = describe_figures_in_graph("lib-t", "doc-1", max_workers=1)
        self.assertEqual(stats["described"], 1)
        self.assertEqual(stats["already"], 1)
        mock_desc.assert_called_once()

        # 写回校验
        lines = [json.loads(l) for l in
                 (self._graph_dir() / "doc_blocks_graph.jsonl").read_text(encoding="utf-8").splitlines()]
        by_uid = {n["block_uid"]: n for n in lines}
        self.assertEqual(by_uid["f2"]["figure_description"], "新描述")
        self.assertEqual(by_uid["f1"]["figure_description"], "已有描述")
        self.assertNotIn("figure_description", by_uid["p1"])

        # 断点续跑：全部已有 → 不再调 VLM
        with patch("docs_core.step04_structure.figure_describer.describe_image",
                   return_value="x") as mock_desc2:
            stats2 = describe_figures_in_graph("lib-t", "doc-1", max_workers=1)
        self.assertEqual(stats2["described"], 0)
        mock_desc2.assert_not_called()

    def test_missing_image_tolerated_no_raise(self):
        graph_dir = self._graph_dir()
        _write_graph(graph_dir, [
            {"block_uid": "f1", "block_type": "image", "image_path": "images/none.jpg"},
        ])
        stats = describe_figures_in_graph("lib-t", "doc-1", max_workers=1)
        self.assertEqual(stats["missing_images"], 1)
        self.assertEqual(stats["described"], 0)

    def test_all_failed_raises_for_stage_failure(self):
        graph_dir = self._graph_dir()
        (graph_dir / "images").mkdir(parents=True, exist_ok=True)
        (graph_dir / "images" / "a.jpg").write_bytes(b"fake")
        _write_graph(graph_dir, [
            {"block_uid": "f1", "block_type": "image", "image_path": "images/a.jpg"},
        ])
        with patch("docs_core.step04_structure.figure_describer.describe_image",
                   side_effect=RuntimeError("502")):
            with self.assertRaises(RuntimeError):
                describe_figures_in_graph("lib-t", "doc-1", max_workers=1)


class FigureDescribeStageRegistrationTests(unittest.TestCase):
    def test_stage_registered_soft_between_structure_and_fts(self):
        stage = STAGE_REGISTRY.get("figure_describe")
        self.assertIsNotNone(stage)
        self.assertEqual(stage.kind, STAGE_KIND_SOFT)
        self.assertEqual(stage.depends_on, ["structure"])
        order = resolve_stage_order("all")
        self.assertLess(order.index("structure"), order.index("figure_describe"))
        self.assertLess(order.index("figure_describe"), order.index("fts"))

    def test_legacy_doc_without_stage_record_still_completed(self):
        status = derive_overall_status({
            key: "completed" for key in (
                "source_prep", "convert", "raw_parse", "popo", "structure",
                "fts", "vectors", "graph",
            )
        })
        self.assertEqual(status, "completed")

    def test_legacy_doc_soft_failed_still_partial(self):
        existing = {
            key: "completed" for key in (
                "source_prep", "convert", "raw_parse", "popo", "structure", "fts", "graph",
            )
        }
        existing["vectors"] = "failed"
        self.assertEqual(derive_overall_status(existing), "partial")


class CanonicalBuilderFigureTextTests(unittest.TestCase):
    def _block(self, **overrides):
        block = {
            "block_uid": "f1",
            "block_type": "image",
            "text": "Fig. 1 caption",
            "image_path": "images/a.jpg",
        }
        block.update(overrides)
        return block

    def test_caption_plus_description_concatenated(self):
        blocks = build_canonical_blocks_from_source("doc-1", [
            self._block(figure_description="VLM 描述内容"),
        ])
        self.assertEqual(blocks[0].text, "Fig. 1 caption\nVLM 描述内容")

    def test_description_only_when_no_caption(self):
        blocks = build_canonical_blocks_from_source("doc-1", [
            self._block(text="", figure_description="VLM 描述内容"),
        ])
        self.assertEqual(blocks[0].text, "VLM 描述内容")

    def test_caption_only_unchanged(self):
        blocks = build_canonical_blocks_from_source("doc-1", [self._block()])
        self.assertEqual(blocks[0].text, "Fig. 1 caption")

    def test_no_image_path_ignores_description(self):
        blocks = build_canonical_blocks_from_source("doc-1", [
            self._block(image_path="", figure_description="VLM 描述内容"),
        ])
        self.assertEqual(blocks[0].text, "Fig. 1 caption")


if __name__ == "__main__":
    unittest.main()
