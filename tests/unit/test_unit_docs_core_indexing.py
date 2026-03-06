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
from main import _extract_structured_items_from_markdown


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
            self.assertIn(f"libraries{os.sep}{lib_id}{os.sep}docs{os.sep}{doc_id}{os.sep}source", source_path)

            parsed_path = storage.save_markdown(lib_id, doc_id, "# 标题\n\n内容")
            self.assertTrue(Path(parsed_path).exists())
            self.assertTrue((Path(temp_dir) / "libraries" / lib_id / "docs" / doc_id / "edited" / "current.md").exists())

            edited_path = storage.save_edited_markdown(lib_id, doc_id, "# 标题\n\n修订内容")
            self.assertTrue(Path(edited_path).exists())
            self.assertEqual(storage.read_markdown(lib_id, doc_id), "# 标题\n\n修订内容")

            documents = storage.list_documents(lib_id)
            self.assertEqual(len(documents), 1)
            self.assertEqual(documents[0]["id"], doc_id)
            self.assertTrue(documents[0]["has_markdown"])


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
        items = _extract_structured_items_from_markdown(markdown)
        types = {item["item_type"] for item in items}
        self.assertIn("heading", types)
        self.assertIn("clause", types)
        self.assertIn("table", types)
        self.assertIn("image", types)


if __name__ == "__main__":
    unittest.main()
