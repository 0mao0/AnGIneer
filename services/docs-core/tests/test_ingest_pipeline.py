"""解析主链 staging 与取消能力测试。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

DOCS_CORE_SRC = Path(__file__).resolve().parents[1] / "src"
API_SERVER_SRC = Path(__file__).resolve().parents[2] / "api-server"
if str(DOCS_CORE_SRC) not in sys.path:
    sys.path.insert(0, str(DOCS_CORE_SRC))
if str(API_SERVER_SRC) not in sys.path:
    sys.path.insert(0, str(API_SERVER_SRC))

import knowledge_routes
from docs_core.ingest.store.assets_file_store import FileStorage, resolve_structured_input_dir


class IngestPipelineTests(unittest.TestCase):
    """覆盖解析输入兼容、原子提交与取消任务。"""

    def test_resolve_structured_input_dir_accepts_content_list_v1(self) -> None:
        """content_list.json 应被视为有效结构化输入。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            raw_dir = Path(temp_dir)
            (raw_dir / "content_list.json").write_text("[]", encoding="utf-8")
            resolved = resolve_structured_input_dir(raw_dir)
            self.assertEqual(resolved / "content_list.json", raw_dir / "content_list.json")

    def test_save_parse_artifacts_replaces_previous_parsed_directory(self) -> None:
        """staging 替换后不应残留旧 parsed 目录垃圾文件。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = FileStorage(base_dir=temp_dir)
            parsed_dir = storage.get_parsed_dir("default", "doc-1")
            legacy_file = parsed_dir / "legacy.txt"
            legacy_file.write_text("stale", encoding="utf-8")

            output_dir = Path(temp_dir) / "parse-output"
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "content_list.json").write_text(json.dumps([], ensure_ascii=False), encoding="utf-8")
            (output_dir / "layout.json").write_text(json.dumps({"pdf_info": []}, ensure_ascii=False), encoding="utf-8")
            (output_dir / "model.json").write_text(json.dumps([], ensure_ascii=False), encoding="utf-8")

            final_files = storage.save_parse_artifacts("default", "doc-1", str(output_dir))
            replaced_dir = storage.get_parsed_dir("default", "doc-1")

            self.assertFalse(legacy_file.exists())
            self.assertTrue((replaced_dir / "mineru_raw" / "content_list.json").exists())
            self.assertIn("content_list.json", final_files)

    def test_cancel_requested_stops_before_indexing(self) -> None:
        """收到取消请求后，后台任务不应继续构建结构化索引。"""
        orchestrator = knowledge_routes.ParseOrchestrator()
        mock_service = Mock()
        mock_service.is_parse_task_cancel_requested.side_effect = [False, True]

        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "doc.pdf"
            source_path.write_bytes(b"%PDF-1.4\n")
            md_path = Path(temp_dir) / "content.md"
            md_path.write_text("# demo", encoding="utf-8")

            with (
                patch.object(knowledge_routes, "get_knowledge_service", return_value=mock_service),
                patch.object(
                    knowledge_routes.file_storage,
                    "ensure_doc_source_file",
                    return_value=str(source_path),
                ),
                patch.object(
                    knowledge_routes.file_storage,
                    "save_markdown",
                    return_value=str(md_path),
                ),
                patch.object(
                    knowledge_routes.file_storage,
                    "save_parse_artifacts",
                    return_value={"content_list.json": str(md_path)},
                ),
                patch.object(
                    knowledge_routes.mineru_parser,
                    "parse_to_raw_artifacts",
                    return_value={"success": True, "md_file": str(md_path)},
                ),
                patch.object(knowledge_routes, "build_structured_index_for_doc") as build_index,
            ):
                orchestrator._run_parse_task(
                    task_id="task-1",
                    library_id="default",
                    doc_id="doc-1",
                    file_path=str(source_path),
                    parse_options={"use_llm": False},
                )

        build_index.assert_not_called()
        cancelled_calls = [
            call.kwargs
            for call in mock_service.update_parse_task.call_args_list
            if call.kwargs.get("status") == "cancelled"
        ]
        self.assertTrue(cancelled_calls)



class TagRulesTest(unittest.TestCase):
    """覆盖 tag_rules 信号提取。"""

    def test_infer_entity_tags_detects_must(self) -> None:
        from docs_core.ingest.organize.tag_rules import infer_entity_tags, infer_conditions
        text = "严禁在施工期间拆除支撑"
        tags = infer_entity_tags(text)
        self.assertIn("强制性条文", tags)

    def test_infer_entity_tags_detects_earthquake(self) -> None:
        from docs_core.ingest.organize.tag_rules import infer_entity_tags
        text = "本规程适用于抗震设防烈度为6度"
        tags = infer_entity_tags(text)
        self.assertIn("抗震", tags)

    def test_infer_conditions_mandatory(self) -> None:
        from docs_core.ingest.organize.tag_rules import infer_conditions
        tags = infer_conditions("必须采用甲级资质")
        self.assertIn("强制性条文", tags)

    def test_infer_entity_tags_from_section_path(self) -> None:
        from docs_core.ingest.organize.tag_rules import infer_entity_tags
        tags = infer_entity_tags("", "第三章 / 换算 / 第一節")
        self.assertIn("换算", tags)

    def test_builder_passes_tags_to_block(self) -> None:
        from docs_core.ingest.organize.builder import build_canonical_blocks_from_source
        blocks = build_canonical_blocks_from_source("doc-1", [
            {"block_uid": "b1", "text": "应遵守本规程要求", "section_path": "第一章 / 总则"},
        ])
        self.assertEqual(len(blocks), 1)
        self.assertTrue(blocks[0].entity_tags, "block 应有 entity_tags")
        self.assertTrue(blocks[0].conditions, "block 应有 conditions")


if __name__ == "__main__":
    unittest.main()
