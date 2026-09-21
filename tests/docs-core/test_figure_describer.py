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
    describe_image,
    is_enabled,
    vlm_configs,
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

    def test_vlm_configs_empty_when_unconfigured(self):
        """未配置任何端点时返回空列表——不再内置硬编码 company 端点
        （2026-09-21 实踩：默认 ai.bim-ace.com + ANGINEER_CHAT_API_KEY 等于没配置就静默走 company）。"""
        with _env(FIGURE_DESCRIBE_CONFIGS="", FIGURE_DESCRIBE_VLM_URL=""):
            self.assertEqual(vlm_configs(), [])

    def test_vlm_configs_json_array_order_is_priority(self):
        configs_json = json.dumps([
            {"name": "dgx", "url": "https://dgx/chat/completions", "api_key": "k1", "model": "m1"},
            {"name": "company", "url": "https://company/chat/completions", "api_key": "k2", "model": "m2"},
        ])
        with _env(FIGURE_DESCRIBE_CONFIGS=configs_json):
            configs = vlm_configs()
        self.assertEqual([c["name"] for c in configs], ["dgx", "company"])
        self.assertEqual(configs[0]["model"], "m1")

    def test_vlm_configs_skips_entries_without_url_or_model(self):
        configs_json = json.dumps([
            {"name": "no-url", "model": "m"},
            {"name": "no-model", "url": "https://x/chat/completions"},
            {"name": "ok", "url": "https://ok/chat/completions", "model": "m"},
        ])
        with _env(FIGURE_DESCRIBE_CONFIGS=configs_json):
            self.assertEqual([c["name"] for c in vlm_configs()], ["ok"])

    def test_vlm_configs_invalid_json_falls_back_to_legacy(self):
        with _env(FIGURE_DESCRIBE_CONFIGS="{not-json", FIGURE_DESCRIBE_VLM_URL="https://legacy/chat/completions",
                  FIGURE_DESCRIBE_VLM_API_KEY="", ANGINEER_CHAT_API_KEY="chat-key"):
            os.environ.pop("FIGURE_DESCRIBE_VLM_MODEL", None)
            configs = vlm_configs()
        self.assertEqual(len(configs), 1)
        self.assertEqual(configs[0]["url"], "https://legacy/chat/completions")
        self.assertEqual(configs[0]["api_key"], "chat-key")
        self.assertEqual(configs[0]["model"], "Qwen3.6-35B-A3B-FP8")

    def test_vlm_configs_legacy_single_var_still_works(self):
        with _env(FIGURE_DESCRIBE_CONFIGS="", FIGURE_DESCRIBE_VLM_URL="https://legacy/chat/completions",
                  FIGURE_DESCRIBE_VLM_API_KEY="fig-key", ANGINEER_CHAT_API_KEY=""):
            configs = vlm_configs()
        self.assertEqual(len(configs), 1)
        self.assertEqual(configs[0]["api_key"], "fig-key")


class DescribeImageFailoverTests(unittest.TestCase):
    """多端点故障转移：第一端点失败必须落到第二端点，全部失败抛聚合错误。"""

    def _image(self, tmp: Path) -> Path:
        p = tmp / "a.png"
        p.write_bytes(b"fake-png")
        return p

    def _configs_env(self):
        return _env(FIGURE_DESCRIBE_CONFIGS=json.dumps([
            {"name": "dgx", "url": "https://dgx/chat/completions", "api_key": "k1", "model": "m1"},
            {"name": "company", "url": "https://company/chat/completions", "api_key": "k2", "model": "m2"},
        ]))

    def _resp(self, text):
        import requests as _rq

        resp = _rq.Response()
        resp.status_code = 200
        resp._content = json.dumps({"choices": [{"message": {"content": text}}]}).encode("utf-8")
        return resp

    def test_first_endpoint_wins_without_fallback(self):
        with tempfile.TemporaryDirectory() as td, self._configs_env():
            with patch("docs_core.step04_structure.figure_describer.requests.post",
                       return_value=self._resp("描述")) as mock_post:
                self.assertEqual(describe_image(self._image(Path(td))), "描述")
            mock_post.assert_called_once()
            self.assertEqual(mock_post.call_args.args[0], "https://dgx/chat/completions")

    def test_failover_to_second_endpoint(self):
        import requests as _rq

        with tempfile.TemporaryDirectory() as td, self._configs_env():
            with patch("docs_core.step04_structure.figure_describer.requests.post",
                       side_effect=[_rq.exceptions.ConnectionError("down"), self._resp("兜底描述")]) as mock_post:
                self.assertEqual(describe_image(self._image(Path(td))), "兜底描述")
            self.assertEqual(mock_post.call_count, 2)
            self.assertEqual(mock_post.call_args.args[0], "https://company/chat/completions")

    def test_all_endpoints_failed_raises_aggregated(self):
        import requests as _rq

        with tempfile.TemporaryDirectory() as td, self._configs_env():
            with patch("docs_core.step04_structure.figure_describer.requests.post",
                       side_effect=_rq.exceptions.ConnectionError("down")):
                with self.assertRaises(RuntimeError) as ctx:
                    describe_image(self._image(Path(td)))
        self.assertIn("dgx", str(ctx.exception))
        self.assertIn("company", str(ctx.exception))

    def test_unconfigured_raises_clear_error(self):
        with tempfile.TemporaryDirectory() as td, _env(FIGURE_DESCRIBE_CONFIGS="", FIGURE_DESCRIBE_VLM_URL=""):
            with self.assertRaises(RuntimeError) as ctx:
                describe_image(self._image(Path(td)))
        self.assertIn("FIGURE_DESCRIBE_CONFIGS", str(ctx.exception))


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
