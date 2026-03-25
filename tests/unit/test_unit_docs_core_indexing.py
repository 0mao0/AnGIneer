"""
单元测试：docs-core 存储与结构化索引能力。
"""
import os
import sys
import tempfile
import unittest
import gc
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "services" / "docs-core" / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "apps" / "api-server"))

from docs_core.storage.file_storage import FileStorage
from docs_core.api.knowledge_api import KnowledgeService, KnowledgeNode
from docs_core.storage.structured_strategy import (
    extract_structured_items_from_markdown,
    _build_a_structured_segment_items
)
from docs_core.parser.mineru_structure import (
    A1StructureResult,
    build_graph_from_mineru,
    collect_media_related_block_refs
)


class IsolatedKnowledgeService(KnowledgeService):
    """隔离数据库路径的 KnowledgeService。"""

    def __init__(self, db_path: Path):
        self._isolated_db_path = db_path
        super().__init__()

    def _resolve_db_path(self) -> Path:
        """返回测试专用数据库路径。"""
        self._isolated_db_path.parent.mkdir(parents=True, exist_ok=True)
        return self._isolated_db_path


class TestFileStorage(unittest.TestCase):
    """测试一文档一目录存储。"""

    def test_save_and_read_document_files(self):
        """测试源文件、Markdown 与编辑版读写。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = FileStorage(base_dir=temp_dir)
            lib_id = "default"
            doc_id = "doc-1001"

            source_path = storage.save_source_file(lib_id, doc_id, b"hello", "demo.docx")
            self.assertTrue(Path(source_path).exists())
            self.assertIn(f"libraries{os.sep}{lib_id}{os.sep}documents{os.sep}{doc_id}{os.sep}source", source_path)

            parsed_path = storage.save_markdown(lib_id, doc_id, "# 标题\n\n内容")
            self.assertTrue(Path(parsed_path).exists())
            self.assertTrue((Path(temp_dir) / "libraries" / lib_id / "documents" / doc_id / "edited" / "current.md").exists())

            edited_path = storage.save_edited_markdown(lib_id, doc_id, "# 标题\n\n修订内容")
            self.assertTrue(Path(edited_path).exists())
            self.assertEqual(storage.read_markdown(lib_id, doc_id), "# 标题\n\n修订内容")

            documents = storage.list_documents(lib_id)
            self.assertEqual(len(documents), 1)
            self.assertEqual(documents[0]["id"], doc_id)
            self.assertTrue(documents[0]["has_markdown"])

    def test_manifest_contains_raw_and_middle(self):
        """测试清单字段包含 raw_dir 与 middle_json。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = FileStorage(base_dir=temp_dir)
            lib_id = "default"
            doc_id = "doc-1002"

            storage.save_markdown(lib_id, doc_id, "# 标题\n\n内容")
            storage.save_middle_json(lib_id, doc_id, {"schema_version": "middle.v1", "doc_id": doc_id})
            raw_dir = Path(storage.save_raw_artifacts(lib_id, doc_id, source_dir=""))

            manifest = storage.get_doc_manifest(lib_id, doc_id)
            self.assertIsInstance(manifest, dict)
            self.assertIn("raw_dir", manifest)
            self.assertIn("middle_json", manifest)
            self.assertEqual(manifest.get("raw_dir"), str(raw_dir))
            self.assertTrue(Path(manifest.get("middle_json") or "").exists())


class TestStructuredSegments(unittest.TestCase):
    """测试结构化片段数据服务。"""

    def test_save_query_and_stats_segments(self):
        """测试结构化片段的保存、查询和统计。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "knowledge.sqlite3"
            service = IsolatedKnowledgeService(db_path)
            node = KnowledgeNode(
                id="doc-2001",
                title="测试文档",
                type="document",
                library_id="default",
                status="completed"
            )
            service.create_node(node)

            items = [
                {"item_type": "heading", "title": "第一章", "content": "第一章", "meta": {"level": 1}, "order_index": 0},
                {"item_type": "table", "title": "表格1", "content": "|A|B|\n|-|-|\n|1|2|", "meta": {"line": 10}, "order_index": 1},
                {"item_type": "segment", "title": "段落1", "content": "这是用于检索的段落内容。", "meta": {"line": 20}, "order_index": 2},
            ]
            saved_count = service.save_document_segments("doc-2001", "default", "A_structured", items)
            self.assertEqual(saved_count, 3)

            all_items = service.list_document_segments("doc-2001", "A_structured")
            self.assertEqual(len(all_items), 3)
            table_items = service.list_document_segments("doc-2001", "A_structured", item_type="table")
            self.assertEqual(len(table_items), 1)
            keyword_items = service.list_document_segments("doc-2001", "A_structured", keyword="检索")
            self.assertEqual(len(keyword_items), 1)

            stats = service.get_document_segment_stats("doc-2001")
            self.assertEqual(stats["total"], 3)
            self.assertEqual(stats["strategies"]["A_structured"]["heading"], 1)

            deleted = service.clear_document_segments("doc-2001", "A_structured")
            self.assertEqual(deleted, 3)
            self.assertEqual(len(service.list_document_segments("doc-2001", "A_structured")), 0)
            del service
            gc.collect()

    # 测试 A_structured 索引行会被转换为带精确定位元数据的结构化条目。
    def test_build_a_structured_segment_items_contains_exact_refs(self):
        """测试 A_structured 条目会输出 block_uid、node_id 等精确引用。"""
        result = A1StructureResult(
            nodes=[
                {
                    "id": "doc-1:0:3",
                    "block_uid": "doc-1:0:3",
                    "block_type": "title",
                    "page_idx": 0,
                    "block_seq": 3,
                    "plain_text": "1 总则",
                    "bbox": [0.1, 0.2, 0.3, 0.4],
                    "bbox_source": "layout",
                    "derived_by": "rule",
                    "confidence": 0.95
                }
            ],
            index_rows=[
                {
                    "block_uid": "doc-1:0:3",
                    "block_type": "title",
                    "page_idx": 0,
                    "block_seq": 3,
                    "plain_text": "1 总则",
                    "derived_level": 1,
                    "title_path": "1 总则",
                    "parent_uid": None
                }
            ],
            stats={
                "derived_rows": [
                    {
                        "block_uid": "doc-1:0:3",
                        "page_seq": 1,
                        "parent_block_uid": None,
                        "title_path": "1 总则"
                    }
                ]
            }
        )

        items = _build_a_structured_segment_items(result)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], "doc-1:0:3")
        self.assertEqual(items[0]["item_type"], "title")
        self.assertEqual(items[0]["meta"]["block_uid"], "doc-1:0:3")
        self.assertEqual(items[0]["meta"]["node_id"], "doc-1:0:3")
        self.assertEqual(items[0]["meta"]["page_seq"], 1)
        self.assertEqual(items[0]["meta"]["block_seq"], 3)
        self.assertEqual(items[0]["meta"]["level"], 1)

    def test_build_a_structured_segment_items_contains_caption_and_footnote_refs(self):
        """测试图表条目会输出 caption 与 footnote 的显式 block_uid 引用。"""
        result = A1StructureResult(
            nodes=[
                {
                    "id": "doc-1:0:10",
                    "block_uid": "doc-1:0:10",
                    "block_type": "table",
                    "page_idx": 0,
                    "block_seq": 10,
                    "plain_text": "表1 测试表 注：口径说明",
                    "bbox": [0.1, 0.2, 0.3, 0.4],
                    "bbox_source": "layout",
                    "derived_by": "rule",
                    "confidence": 0.92,
                    "caption_block_uids": ["doc-1:0:11"],
                    "footnote_block_uids": ["doc-1:0:12"]
                }
            ],
            index_rows=[
                {
                    "block_uid": "doc-1:0:10",
                    "block_type": "table",
                    "page_idx": 0,
                    "block_seq": 10,
                    "plain_text": "表1 测试表 注：口径说明",
                    "derived_level": None,
                    "title_path": None,
                    "parent_uid": None,
                    "caption_block_uids": ["doc-1:0:11"],
                    "footnote_block_uids": ["doc-1:0:12"]
                }
            ],
            stats={
                "base_rows": [
                    {
                        "block_uid": "doc-1:0:10",
                        "block_type": "table",
                        "page_idx": 0,
                        "content_json": {
                            "table_caption": [{"content": "表1 测试表"}],
                            "table_footnote": [{"content": "注：口径说明"}]
                        }
                    },
                    {
                        "block_uid": "doc-1:0:11",
                        "block_type": "paragraph",
                        "page_idx": 0,
                        "plain_text": "表1 测试表"
                    },
                    {
                        "block_uid": "doc-1:0:12",
                        "block_type": "paragraph",
                        "page_idx": 0,
                        "plain_text": "注：口径说明"
                    }
                ],
                "derived_rows": [
                    {
                        "block_uid": "doc-1:0:10",
                        "page_seq": 1,
                        "parent_block_uid": None,
                        "title_path": None,
                        "caption_block_uids": ["doc-1:0:11"],
                        "footnote_block_uids": ["doc-1:0:12"]
                    }
                ]
            }
        )

        items = _build_a_structured_segment_items(result)

        self.assertEqual(items[0]["meta"]["caption_block_uid"], "doc-1:0:11")
        self.assertEqual(items[0]["meta"]["caption_block_uids"], ["doc-1:0:11"])
        self.assertEqual(items[0]["meta"]["footnote_block_uid"], "doc-1:0:12")
        self.assertEqual(items[0]["meta"]["footnote_block_uids"], ["doc-1:0:12"])

    def test_collect_media_related_block_refs_from_parser_rows(self):
        """测试解析阶段会为图表块直接产出 caption 与 footnote 的关联 refs。"""
        rows = [
            {
                "block_uid": "doc-1:0:10",
                "block_type": "image",
                "page_idx": 0,
                "content_json": {
                    "image_caption": [{"content": "图1 系统架构"}],
                    "image_footnote": [{"content": "来源：测试环境"}]
                }
            },
            {
                "block_uid": "doc-1:0:11",
                "block_type": "paragraph",
                "page_idx": 0,
                "plain_text": "图1 系统架构"
            },
            {
                "block_uid": "doc-1:0:12",
                "block_type": "paragraph",
                "page_idx": 0,
                "plain_text": "来源：测试环境"
            }
        ]

        refs = collect_media_related_block_refs(rows[0], rows)

        self.assertEqual(refs["caption_block_uids"], ["doc-1:0:11"])
        self.assertEqual(refs["footnote_block_uids"], ["doc-1:0:12"])

    # 测试解析阶段会优先按顺序而非按文本把 model.json 的 bbox 对齐回来。
    def test_build_graph_from_mineru_enriches_caption_and_footnote_bboxes(self):
        """测试 build_graph_from_mineru 会优先按顺序把 model.json 中的图表题注 bbox 写入结果。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            parsed_dir = Path(temp_dir)
            raw_dir = parsed_dir / "mineru_raw"
            raw_dir.mkdir(parents=True, exist_ok=True)

            (raw_dir / "content_list_v2.json").write_text(
                """
[
  [
    {
      "type": "table",
      "bbox": [100, 200, 500, 600],
      "content": {
        "table_caption": [{"content": "表1 测试表"}],
        "table_footnote": [{"content": "注：口径说明"}]
      }
    },
    {
      "type": "paragraph",
      "bbox": [110, 610, 380, 640],
      "content": {
        "paragraph_content": [{"content": "表1 测试表"}]
      }
    },
    {
      "type": "paragraph",
      "bbox": [110, 645, 420, 675],
      "content": {
        "paragraph_content": [{"content": "注：口径说明"}]
      }
    }
  ]
]
                """.strip(),
                encoding="utf-8"
            )
            (raw_dir / "layout.json").write_text(
                """
{
  "_version_name": "test-layout",
  "pdf_info": [
    {
      "page_idx": 0,
      "page_size": [1000, 1000]
    }
  ]
}
                """.strip(),
                encoding="utf-8"
            )
            (raw_dir / "model.json").write_text(
                """
[
  [
    {
      "type": "table_caption",
      "bbox": [0.11, 0.61, 0.38, 0.64],
      "content": "与 content_list 不同的 caption 文本"
    },
    {
      "type": "table",
      "bbox": [0.10, 0.20, 0.50, 0.60],
      "content": "<table><tr><td>A</td></tr></table>"
    },
    {
      "type": "table_footnote",
      "bbox": [0.11, 0.645, 0.42, 0.675],
      "content": "与 content_list 不同的 footnote 文本"
    }
  ]
]
                """.strip(),
                encoding="utf-8"
            )

            result = build_graph_from_mineru(parsed_dir, "doc-test", "测试文档", llm_client=None, options={"use_llm": False})

            self.assertEqual(len(result.nodes), 3)
            table_node = next(node for node in result.nodes if node["block_type"] == "table")
            table_index = next(row for row in result.index_rows if row["block_type"] == "table")
            base_row = next(row for row in result.stats["base_rows"] if row["block_type"] == "table")
            derived_row = next(row for row in result.stats["derived_rows"] if row["block_uid"] == table_node["block_uid"])

            expected_caption_bbox = [[0.11, 0.61, 0.38, 0.64]]
            expected_footnote_bbox = [[0.11, 0.645, 0.42, 0.675]]

            self.assertEqual(base_row["content_json"]["table_caption_bboxes"], expected_caption_bbox)
            self.assertEqual(base_row["content_json"]["table_footnote_bboxes"], expected_footnote_bbox)
            self.assertEqual(table_node["caption_bboxes"], expected_caption_bbox)
            self.assertEqual(table_node["footnote_bboxes"], expected_footnote_bbox)
            self.assertEqual(table_index["caption_bboxes"], expected_caption_bbox)
            self.assertEqual(table_index["footnote_bboxes"], expected_footnote_bbox)
            self.assertEqual(derived_row["caption_bboxes"], expected_caption_bbox)
            self.assertEqual(derived_row["footnote_bboxes"], expected_footnote_bbox)


class TestMarkdownExtractor(unittest.TestCase):
    """测试 Markdown 结构化提取。"""

    def test_extract_items_from_markdown(self):
        """测试标题、条款、表格、图片提取。"""
        markdown = """# 总则

1.1 适用范围
本规范适用于测试场景，包含多个字段说明。

| 字段 | 含义 |
| --- | --- |
| A | 值 |

![设备图](assets/a.png "图1")
"""
        items = extract_structured_items_from_markdown(markdown)
        types = {item["item_type"] for item in items}
        self.assertIn("heading", types)
        self.assertIn("clause", types)
        self.assertIn("table", types)
        self.assertIn("image", types)


if __name__ == "__main__":
    unittest.main()
