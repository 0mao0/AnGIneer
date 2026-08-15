"""
单元测试：docs-core 存储与结构化索引能力。
"""
import os
import sys
import tempfile
import unittest
import gc
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "services" / "docs-core" / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "apps" / "api-server"))

import docs_core.paths as paths
from docs_core.docs_file_io import FileStorage
import docs_core.docs_file_io as fs_module
import docs_core.step05_sqlite_fts.graph_editor as graph_module
import importlib

# docs_core/__init__.py 会把 docs_service 属性遮蔽为代理对象，
# 这里必须取真实模块才能 patch 模块级 docs_service 属性。
docs_service_module = importlib.import_module("docs_core.docs_service")
from docs_core.docs_service import DocsService, KnowledgeNode
from docs_core.step05_sqlite_fts.graph_editor import (
    _build_structured_segment_items_from_graph,
    batch_operate_doc_blocks,
    undo_last_doc_block_merge,
)
from docs_core.step04_structure.shared.formula_semantics import (
    build_formula_representations,
    parse_formula_param_rule,
)
from docs_core.step04_structure.solo_engine import (
    StructuredResult,
    build_structured_from_rawfiles,
    collect_media_related_block_refs
)
from docs_core.step03_mineru_parse.mineru_parser import save_markdown


_ORIGINAL_VECTORSTORE = os.environ.get("DOCS_VECTORSTORE_PROVIDER")


def setUpModule() -> None:
    """存储/批量编辑测试统一使用 SQLite 向量后端，避免 Chroma 连接锁住临时目录。"""
    os.environ["DOCS_VECTORSTORE_PROVIDER"] = "sqlite"


def _write_graph_files(library_id: str, doc_id: str, graph_data, base_dir: str) -> None:
    """按 jsonl + meta 格式落盘图数据（与写入侧对齐）。"""
    jsonl_path = paths.get_graph_jsonl_path(library_id, doc_id, base_dir=base_dir)
    meta_path = paths.get_graph_meta_path(library_id, doc_id, base_dir=base_dir)
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for node in graph_data.get("nodes", []):
            f.write(json.dumps(node, ensure_ascii=False) + "\n")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(
            {"edges": graph_data.get("edges", []), "stats": graph_data.get("stats", {})},
            f, ensure_ascii=False, indent=2,
        )


def tearDownModule() -> None:
    if _ORIGINAL_VECTORSTORE is None:
        os.environ.pop("DOCS_VECTORSTORE_PROVIDER", None)
    else:
        os.environ["DOCS_VECTORSTORE_PROVIDER"] = _ORIGINAL_VECTORSTORE


class IsolatedDocsService(DocsService):
    """隔离数据库路径的 DocsService。"""

    def __init__(self, db_path: Path):
        self._isolated_db_path = db_path
        self._isolated_index_db_path = db_path.parent / "knowledge_index.sqlite"
        super().__init__()

    def _resolve_db_path(self) -> Path:
        """返回测试专用数据库路径。"""
        self._isolated_db_path.parent.mkdir(parents=True, exist_ok=True)
        return self._isolated_db_path

    def _resolve_index_db_path(self) -> Path:
        """返回测试专用索引数据库路径。"""
        self._isolated_index_db_path.parent.mkdir(parents=True, exist_ok=True)
        return self._isolated_index_db_path


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

            parsed_path = save_markdown(lib_id, doc_id, "# 标题\n\n内容", base_dir=temp_dir)
            self.assertTrue(Path(parsed_path).exists())
            self.assertTrue((Path(temp_dir) / "libraries" / lib_id / "documents" / doc_id / "edited" / "current.md").exists())

            edited_path = storage.save_edited_markdown(lib_id, doc_id, "# 标题\n\n修订内容")
            self.assertTrue(Path(edited_path).exists())
            self.assertEqual(storage.read_markdown(lib_id, doc_id), "# 标题\n\n修订内容")

            documents = storage.list_documents(lib_id)
            self.assertEqual(len(documents), 1)
            self.assertEqual(documents[0]["id"], doc_id)
            self.assertTrue(documents[0]["has_markdown"])

    def test_manifest_contains_raw_and_blocks(self):
        """测试清单字段包含 raw_dir mineru_blocks。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = FileStorage(base_dir=temp_dir)
            lib_id = "default"
            doc_id = "doc-1002"

            save_markdown(lib_id, doc_id, "# 标题\n\n内容", base_dir=temp_dir)
            raw_dir = paths.get_raw_dir(lib_id, doc_id, temp_dir)
            raw_dir.mkdir(parents=True, exist_ok=True)

            manifest = storage.get_doc_manifest(lib_id, doc_id)
            self.assertIsInstance(manifest, dict)
            self.assertIn("raw_dir", manifest)
            self.assertIn("mineru_blocks", manifest)
            self.assertEqual(manifest.get("raw_dir"), str(raw_dir))


class TestStructuredSegments(unittest.TestCase):
    """测试结构化片段数据服务。"""

    def test_save_query_and_stats_segments(self):
        """测试结构化片段的保存、查询和统计。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "knowledge_meta.sqlite"
            service = IsolatedDocsService(db_path)
            node = KnowledgeNode(
                id="doc-2001",
                title="测试文档",
                type="document",
                library_id="default",
                status="completed"
            )
            service.create_node(node)

            items = [
                {"item_type": "heading", "title": "第一", "content": "第一", "meta": {"level": 1}, "order_index": 0},
                {"item_type": "table", "title": "表格1", "content": "|A|B|\n|-|-|\n|1|2|", "meta": {"line": 10}, "order_index": 1},
                {"item_type": "segment", "title": "段落1", "content": "这是用于检索的段落内容", "meta": {"line": 20}, "order_index": 2},
            ]
            saved_count = service.save_document_segments("doc-2001", "default", "doc_blocks_graph_v1", items)
            self.assertEqual(saved_count, 3)

            all_items = service.list_document_segments("doc-2001", "doc_blocks_graph_v1")
            self.assertEqual(len(all_items), 3)
            table_items = service.list_document_segments("doc-2001", "doc_blocks_graph_v1", item_type="table")
            self.assertEqual(len(table_items), 1)
            keyword_items = service.list_document_segments("doc-2001", "doc_blocks_graph_v1", keyword="检")
            self.assertEqual(len(keyword_items), 1)

            stats = service.get_document_segment_stats("doc-2001")
            self.assertEqual(stats["total"], 3)
            self.assertEqual(stats["strategies"]["doc_blocks_graph_v1"]["heading"], 1)

            deleted = service.clear_document_segments("doc-2001", "doc_blocks_graph_v1")
            self.assertEqual(deleted, 3)
            self.assertEqual(len(service.list_document_segments("doc-2001", "doc_blocks_graph_v1")), 0)
            del service
            gc.collect()

    def test_delete_node_purges_document_storage_and_indexes(self):
        """测试删除节点会同步清理文档目录、任务和索引数据。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "knowledge_meta.sqlite"
            isolated_service = IsolatedDocsService(db_path)
            isolated_storage = FileStorage(base_dir=temp_dir)
            previous_storage = fs_module.file_storage
            fs_module.file_storage = isolated_storage
            try:
                folder = KnowledgeNode(
                    id="folder-1",
                    title="测试文件",
                    type="folder",
                    library_id="default",
                    status="completed"
                )
                isolated_service.create_node(folder)
                source_path = isolated_storage.save_source_file("default", "doc-delete-1", b"hello", "demo.pdf")
                save_markdown("default", "doc-delete-1", "# 标题\n\n内容", base_dir=temp_dir)
                document = KnowledgeNode(
                    id="doc-delete-1",
                    title="待删除文",
                    type="document",
                    parent_id="folder-1",
                    library_id="default",
                    file_path=source_path,
                    status="completed"
                )
                isolated_service.create_node(document)
                isolated_service.create_parse_task("task-delete-1", "default", "doc-delete-1")
                isolated_service.save_document_segments(
                    "doc-delete-1",
                    "default",
                    "doc_blocks_graph_v1",
                    [{"item_type": "segment", "title": "段落", "content": "待清理内"}],
                )
                isolated_service.index_store.insert_doc_blocks_base_rows(
                    [
                        {
                            "doc_id": "doc-delete-1",
                            "doc_name": "待删除文",
                            "page_idx": 0,
                            "page_width": 100.0,
                            "page_height": 200.0,
                            "block_seq": 1,
                            "block_uid": "doc-delete-1:0:1",
                            "block_type": "paragraph",
                            "content_json": {},
                            "plain_text": "待清理块",
                            "bbox_abs_x1": 0.0,
                            "bbox_abs_y1": 0.0,
                            "bbox_abs_x2": 10.0,
                            "bbox_abs_y2": 10.0,
                            "created_at": "2026-01-01T00:00:00",
                            "updated_at": "2026-01-01T00:00:00",
                        }
                    ]
                )
                isolated_service.index_store.record_doc_block_correction(
                    "doc-delete-1",
                    "doc-delete-1:0:1",
                    "delete",
                    {"block_uid": "doc-delete-1:0:1"},
                )

                deleted = isolated_service.delete_node("folder-1")

                self.assertTrue(deleted)
                self.assertIsNone(isolated_service.get_node("folder-1"))
                self.assertIsNone(isolated_service.get_node("doc-delete-1"))
                self.assertEqual(len(isolated_service.parse_tasks), 0)
                self.assertFalse((Path(temp_dir) / "libraries" / "default" / "documents" / "doc-delete-1").exists())
                self.assertEqual(len(isolated_service.meta_store.list_parse_tasks()), 0)
                self.assertEqual(len(isolated_service.list_document_segments("doc-delete-1", "doc_blocks_graph_v1")), 0)
                conn = isolated_service.index_store.connect()
                try:
                    doc_block_count = conn.execute(
                        "SELECT COUNT(1) FROM doc_blocks WHERE doc_id = ?",
                        ("doc-delete-1",),
                    ).fetchone()[0]
                    correction_count = conn.execute(
                        "SELECT COUNT(1) FROM doc_block_corrections WHERE doc_id = ?",
                        ("doc-delete-1",),
                    ).fetchone()[0]
                finally:
                    conn.close()
                self.assertEqual(doc_block_count, 0)
                self.assertEqual(correction_count, 0)
            finally:
                fs_module.file_storage = previous_storage
                del isolated_service
                gc.collect()

    def test_get_delete_preview_returns_recursive_document_summary(self):
        """测试删除预览会返回递归影响范围与文档摘要。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "knowledge_meta.sqlite"
            service = IsolatedDocsService(db_path)
            root_folder = KnowledgeNode(
                id="folder-root",
                title="根文件夹",
                type="folder",
                library_id="default",
                status="completed"
            )
            child_folder = KnowledgeNode(
                id="folder-child",
                title="子文件夹",
                type="folder",
                parent_id="folder-root",
                library_id="default",
                status="completed"
            )
            doc_one = KnowledgeNode(
                id="doc-preview-1",
                title="文档一",
                type="document",
                parent_id="folder-root",
                library_id="default",
                status="completed"
            )
            doc_two = KnowledgeNode(
                id="doc-preview-2",
                title="文档",
                type="document",
                parent_id="folder-child",
                library_id="default",
                status="completed"
            )
            for node in [root_folder, child_folder, doc_one, doc_two]:
                service.create_node(node)

            preview = service.get_delete_preview("folder-root")

            self.assertIsNotNone(preview)
            assert preview is not None
            self.assertEqual(preview["node_id"], "folder-root")
            self.assertEqual(preview["folder_count"], 2)
            self.assertEqual(preview["document_count"], 2)
            self.assertEqual(preview["total_nodes"], 4)
            self.assertEqual(preview["doc_ids"], ["doc-preview-1", "doc-preview-2"])
            self.assertEqual(preview["sample_doc_titles"], ["文档一", "文档"])
            del service
            gc.collect()

    # 测试图谱重建的结构化条目会输出带精确定位元数据的投影
    def test_graph_segment_items_contains_exact_refs(self):
        """测试图 segment 投影输出 block_uid、derived_level 等精确引用。"""
        graph_data = {
            "nodes": [
                {
                    "id": "doc-1:0:3",
                    "block_uid": "doc-1:0:3",
                    "block_type": "title",
                    "page_idx": 0,
                    "block_seq": 3,
                    "plain_text": "1 总则",
                    "title_path": "1 总则",
                    "derived_level": 1,
                }
            ],
            "edges": [],
        }

        items = _build_structured_segment_items_from_graph(graph_data)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], "doc-1:0:3")
        self.assertEqual(items[0]["item_type"], "title")
        self.assertEqual(items[0]["meta"]["block_uid"], "doc-1:0:3")
        self.assertEqual(items[0]["meta"]["page_idx"], 0)
        self.assertEqual(items[0]["meta"]["block_seq"], 3)
        self.assertEqual(items[0]["meta"]["derived_level"], 1)

    def test_graph_segment_items_contains_caption_and_footnote_refs(self):
        """测试图 segment 投影输出图表 caption/footnote 的显式 block_uid 引用。"""
        graph_data = {
            "nodes": [
                {
                    "id": "doc-1:0:10",
                    "block_uid": "doc-1:0:10",
                    "block_type": "table",
                    "page_idx": 0,
                    "block_seq": 10,
                    "plain_text": "测试注：口径说明",
                    "caption_block_uid": "doc-1:0:11",
                    "caption_block_uids": ["doc-1:0:11"],
                    "footnote_block_uid": "doc-1:0:12",
                    "footnote_block_uids": ["doc-1:0:12"],
                }
            ],
            "edges": [],
        }

        items = _build_structured_segment_items_from_graph(graph_data)

        self.assertEqual(items[0]["meta"]["caption_block_uid"], "doc-1:0:11")
        self.assertEqual(items[0]["meta"]["caption_block_uids"], ["doc-1:0:11"])
        self.assertEqual(items[0]["meta"]["footnote_block_uid"], "doc-1:0:12")
        self.assertEqual(items[0]["meta"]["footnote_block_uids"], ["doc-1:0:12"])

    def test_collect_media_related_block_refs_from_parser_rows(self):
        """测试解析阶段会为图表块直接产caption footnote 的关refs。"""
        rows = [
            {
                "block_uid": "doc-1:0:10",
                "block_type": "image",
                "page_idx": 0,
                "content_json": {
                    "image_caption": [{"content": " 系统架构"}],
                    "image_footnote": [{"content": "来源：测试环"}]
                }
            },
            {
                "block_uid": "doc-1:0:11",
                "block_type": "paragraph",
                "page_idx": 0,
                "plain_text": " 系统架构"
            },
            {
                "block_uid": "doc-1:0:12",
                "block_type": "paragraph",
                "page_idx": 0,
                "plain_text": "来源：测试环境",
            }
        ]

        refs = collect_media_related_block_refs(rows[0], rows)

        self.assertEqual(refs["caption_block_uids"], ["doc-1:0:11"])
        self.assertEqual(refs["footnote_block_uids"], ["doc-1:0:12"])

    def test_collect_media_related_block_refs_excludes_struct_heading_rows(self):
        """测试图表关联匹配不会把结构标题误识别为脚注引用。"""
        rows = [
            {
                "block_uid": "doc-1:0:20",
                "block_type": "image",
                "page_idx": 0,
                "content_json": {
                    "image_caption": [{"content": ".4.1 航道设计基本尺度"}],
                    "image_footnote": [{"content": "6.4.2 航道通航宽度应由航迹带宽度确"}]
                }
            },
            {
                "block_uid": "doc-1:0:21",
                "block_type": "title",
                "page_idx": 0,
                "plain_text": "6.4.2 航道通航宽度应由航迹带宽度确定",
            },
            {
                "block_uid": "doc-1:0:22",
                "block_type": "paragraph",
                "page_idx": 0,
                "plain_text": "6.4.2 航道通航宽度应由航迹带宽度确定",
            }
        ]

        refs = collect_media_related_block_refs(rows[0], rows)

        self.assertNotIn("caption_block_uids", refs)
        self.assertNotIn("footnote_block_uids", refs)

    # 测试解析阶段会优先按顺序而非按文本把 model.json bbox 对齐回来
    def test_build_structured_from_rawfiles_enriches_caption_and_footnote_bboxes(self):
        """测试 build_structured_from_rawfiles 会优先按顺序model.json 中的图表题注 bbox 写入结果。"""
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
        "table_caption": [{"content": " 测试"}],
        "table_footnote": [{"content": "注：口径说明"}]
      }
    },
    {
      "type": "paragraph",
      "bbox": [110, 610, 380, 640],
      "content": {
        "paragraph_content": [{"content": " 测试"}]
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
      "content": "content_list 不同caption 文本"
    },
    {
      "type": "table",
      "bbox": [0.10, 0.20, 0.50, 0.60],
      "content": "<table><tr><td>A</td></tr></table>"
    },
    {
      "type": "table_footnote",
      "bbox": [0.11, 0.645, 0.42, 0.675],
      "content": "content_list 不同footnote 文本"
    }
  ]
]
                """.strip(),
                encoding="utf-8"
            )

            result = build_structured_from_rawfiles(parsed_dir, "doc-test", "测试文档", llm_client=None, options={"use_llm": False})

            self.assertEqual(len(result.nodes), 3)
            table_node = next(node for node in result.nodes if node["block_type"] == "table")
            table_index = next(row for row in result.index_rows if row["block_type"] == "table")

            expected_caption_bbox = [[0.11, 0.61, 0.38, 0.64]]
            expected_footnote_bbox = [[0.11, 0.645, 0.42, 0.675]]

            self.assertEqual(table_node["caption_bboxes"], expected_caption_bbox)
            self.assertEqual(table_node["footnote_bboxes"], expected_footnote_bbox)
            self.assertEqual(table_index["caption_bboxes"], expected_caption_bbox)
            self.assertEqual(table_index["footnote_bboxes"], expected_footnote_bbox)


class FakeLLMClient:
    """用于公式兜底测试的最LLM 假对象。"""

    def __init__(self, response_text: str):
        self._response_text = response_text

    def chat(self, *args, **kwargs):
        """返回预设的结构化响应文本。"""
        return self._response_text


class TestFormulaSemantics(unittest.TestCase):
    """测试公式结构化提取与投影。"""

    def test_parse_formula_param_rule(self):
        """测试规则能识别常见公式参数行。"""
        parsed = parse_formula_param_rule("γ——风、流压缩角（^circ），采用.4.2-2中的数")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["symbol"], "γ")
        self.assertIn("风、流压缩", parsed["description"])
        self.assertEqual(parsed["unit"], "^circ")
        self.assertIn(".4.2-2", parsed["reference_hint"])

    def test_build_formula_representations_with_llm_fallback(self):
        """测试规则不足时会启用 LLM 兜底补充参数。"""
        llm_client = FakeLLMClient(
            json.dumps(
                {
                    "params": [
                        {
                            "symbol": "B",
                            "description": "设计槽宽",
                            "unit": "m",
                            "reference_hint": None,
                            "confidence": 0.86,
                        }
                    ]
                },
                ensure_ascii=False,
            )
        )
        result = build_formula_representations(
            formula_text="A = n(Lsinγ + B)",
            explanation_lines=["式中", "槽宽参数 B（m"],
            llm_client=llm_client,
            llm_model="Qwen3.6-35B-A3B (Private)",
            use_llm=True,
        )
        params = result["formula_params"]
        self.assertEqual(len(params), 1)
        self.assertEqual(params[0]["symbol"], "B")
        self.assertEqual(params[0]["unit"], "m")
        self.assertEqual(params[0]["extracted_by"], "llm")
        self.assertEqual(result["llm_status"], "ok")

    def test_graph_segment_items_adds_formula_items(self):
        """测试图 segment 投影会为公式补充摘要和参数条目。"""
        graph_data = {
            "nodes": [
                {
                    "id": "doc-1:0:1",
                    "block_uid": "doc-1:0:1",
                    "block_type": "equation_interline",
                    "page_idx": 0,
                    "block_seq": 1,
                    "plain_text": "A = n(Lsinγ + B)",
                    "math_content": "A = n(Lsinγ + B)",
                },
                {
                    "id": "doc-1:0:2",
                    "block_uid": "doc-1:0:2",
                    "block_type": "paragraph",
                    "page_idx": 0,
                    "block_seq": 2,
                    "plain_text": "式中",
                    "parent_uid": "doc-1:0:1",
                },
                {
                    "id": "doc-1:0:3",
                    "block_uid": "doc-1:0:3",
                    "block_type": "paragraph",
                    "page_idx": 0,
                    "block_seq": 3,
                    "plain_text": "γ——风、流压缩角（^circ），采用表6.4.2-2中的数值",
                    "parent_uid": "doc-1:0:1",
                },
                {
                    "id": "doc-1:0:4",
                    "block_uid": "doc-1:0:4",
                    "block_type": "paragraph",
                    "page_idx": 0,
                    "block_seq": 4,
                    "plain_text": "B——设计槽宽（m）",
                    "parent_uid": "doc-1:0:1",
                },
            ],
            "edges": [],
        }

        items = _build_structured_segment_items_from_graph(graph_data)
        item_types = [item["item_type"] for item in items]
        self.assertIn("equation_interline", item_types)
        self.assertIn("formula_summary", item_types)
        self.assertEqual(item_types.count("formula_param"), 2)
        formula_param_titles = [item["title"] for item in items if item["item_type"] == "formula_param"]
        self.assertIn("γ", formula_param_titles)
        self.assertIn("B", formula_param_titles)


class TestStructuredBatchOperations(unittest.TestCase):
    """测试结构化批量编辑操作。"""

    def test_batch_merge_split_delete_and_undo_blocks(self):
        """测试批量合并、拆分、删除与撤回会同步图谱与结构化投影。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "knowledge_meta.sqlite"
            isolated_service = IsolatedDocsService(db_path)
            isolated_storage = FileStorage(base_dir=temp_dir)
            previous_base_dir = os.environ.get("KNOWLEDGE_BASE_DIR")
            os.environ["KNOWLEDGE_BASE_DIR"] = temp_dir
            previous_service = docs_service_module.docs_service
            previous_storage = fs_module.file_storage
            docs_service_module.docs_service = isolated_service
            fs_module.file_storage = isolated_storage
            try:
                node = KnowledgeNode(
                    id="doc-batch-1",
                    title="批量结构操作测试",
                    type="document",
                    library_id="default",
                    status="completed"
                )
                isolated_service.create_node(node)
                graph_data = {
                    "doc_id": "doc-batch-1",
                    "doc_name": "批量结构操作测试",
                    "nodes": [
                        {
                            "id": "doc-batch-1:0:1",
                            "block_uid": "doc-batch-1:0:1",
                            "block_type": "title",
                            "page_idx": 0,
                            "block_seq": 1,
                            "plain_text": "第一",
                            "bbox": [0.0, 0.0, 1.0, 0.1],
                            "bbox_source": "layout",
                            "derived_level": 1,
                            "title_path": "doc-batch-1:0:1",
                            "parent_uid": None,
                            "derived_by": "rule",
                            "confidence": 0.98,
                            "content_json": {},
                        },
                        {
                            "id": "doc-batch-1:0:2",
                            "block_uid": "doc-batch-1:0:2",
                            "block_type": "image",
                            "page_idx": 0,
                            "block_seq": 2,
                            "plain_text": "段落一",
                            "bbox": [0.0, 0.1, 1.0, 0.2],
                            "bbox_source": "layout",
                            "derived_level": None,
                            "title_path": "doc-batch-1:0:1",
                            "parent_uid": "doc-batch-1:0:1",
                            "derived_by": "rule",
                            "confidence": 0.91,
                            "caption": "图注一",
                            "footnote": "脚注一",
                            "image_path": "assets/img-a.png",
                            "caption_block_uids": ["doc-batch-1:0:4"],
                            "caption_bboxes": [[0.05, 0.08, 0.4, 0.1]],
                            "footnote_block_uids": ["doc-batch-1:0:5"],
                            "footnote_bboxes": [[0.05, 0.2, 0.45, 0.24]],
                            "content_json": {
                                "image_caption": [{"content": "图注一"}],
                                "image_footnote": [{"content": "脚注一"}],
                            },
                        },
                        {
                            "id": "doc-batch-1:0:3",
                            "block_uid": "doc-batch-1:0:3",
                            "block_type": "image",
                            "page_idx": 0,
                            "block_seq": 3,
                            "plain_text": "段落",
                            "bbox": [0.0, 0.2, 1.0, 0.3],
                            "bbox_source": "layout",
                            "derived_level": None,
                            "title_path": "doc-batch-1:0:1",
                            "parent_uid": "doc-batch-1:0:1",
                            "derived_by": "rule",
                            "confidence": 0.9,
                            "caption": "图注",
                            "footnote": "脚注",
                            "image_path": "assets/img-b.png",
                            "caption_block_uids": ["doc-batch-1:0:6"],
                            "caption_bboxes": [[0.06, 0.28, 0.42, 0.31]],
                            "footnote_block_uids": ["doc-batch-1:0:7"],
                            "footnote_bboxes": [[0.06, 0.31, 0.46, 0.34]],
                            "content_json": {
                                "image_caption": [{"content": "图注"}],
                                "image_footnote": [{"content": "脚注"}],
                            },
                        },
                        {
                            "id": "doc-batch-1:1:1",
                            "block_uid": "doc-batch-1:1:1",
                            "block_type": "title",
                            "page_idx": 1,
                            "block_seq": 1,
                            "plain_text": "第二",
                            "bbox": [0.0, 0.0, 1.0, 0.1],
                            "bbox_source": "layout",
                            "derived_level": 1,
                            "title_path": "doc-batch-1:1:1",
                            "parent_uid": None,
                            "derived_by": "rule",
                            "confidence": 0.97,
                            "content_json": {},
                        },
                    ],
                    "edges": [],
                    "stats": {
                        "base_rows": [],
                        "derived_rows": [],
                        "index_rows": [],
                    },
                }
                graph_module._rebuild_graph_projection(graph_data)
                _write_graph_files("default", "doc-batch-1", graph_data, temp_dir)

                merge_result = batch_operate_doc_blocks(
                    "default",
                    "doc-batch-1",
                    "merge",
                    {
                        "operation": "merge",
                        "blockIds": ["doc-batch-1:0:2", "doc-batch-1:0:3"],
                        "targetBlockId": "doc-batch-1:0:2",
                    },
                )
                self.assertEqual(merge_result["removed_block_ids"], ["doc-batch-1:0:3"])
                self.assertEqual(merge_result["target_block_id"], "doc-batch-1:0:2")

                merged_graph = graph_module.get_doc_blocks_graph("default", "doc-batch-1")
                self.assertIsNotNone(merged_graph)
                merged_node_map = {
                    node["block_uid"]: node
                    for node in merged_graph["nodes"]
                    if int(node.get("is_active", 1) or 0) != 0
                }
                merged_target = merged_node_map["doc-batch-1:0:2"]
                self.assertEqual(merged_target["plain_text"], "段落一\n段落")
                self.assertEqual(merged_target["caption"], "图注一\n图注")
                self.assertEqual(merged_target["footnote"], "脚注一\n脚注")
                self.assertEqual(merged_target["image_path"], "assets/img-a.png")
                self.assertEqual(merged_target["image_paths"], ["assets/img-a.png", "assets/img-b.png"])
                self.assertEqual(
                    merged_target["caption_block_uids"],
                    ["doc-batch-1:0:4", "doc-batch-1:0:6"],
                )
                self.assertEqual(
                    merged_target["footnote_block_uids"],
                    ["doc-batch-1:0:5", "doc-batch-1:0:7"],
                )
                self.assertEqual(
                    merged_target["caption_bboxes"],
                    [
                        [0.05, 0.08, 0.4, 0.1],
                        [0.06, 0.28, 0.42, 0.31],
                    ],
                )
                self.assertEqual(
                    merged_target["footnote_bboxes"],
                    [
                        [0.05, 0.2, 0.45, 0.24],
                        [0.06, 0.31, 0.46, 0.34],
                    ],
                )
                self.assertEqual(
                    merged_target["content_json"]["image_caption"],
                    [{"content": "图注一"}, {"content": "图注"}],
                )
                self.assertEqual(merged_target["bbox"], [0.0, 0.1, 1.0, 0.2])
                self.assertEqual(
                    merged_target["merged_bboxes"],
                    [
                        [0.0, 0.1, 1.0, 0.2],
                        [0.0, 0.2, 1.0, 0.3],
                    ],
                )
                self.assertEqual(
                    merged_target["merged_block_uids"],
                    ["doc-batch-1:0:2", "doc-batch-1:0:3"],
                )

                split_result = batch_operate_doc_blocks(
                    "default",
                    "doc-batch-1",
                    "split",
                    {
                        "operation": "split",
                        "blockIds": ["doc-batch-1:0:2"],
                        "splitSegments": [
                            {"plain_text": "段落一"},
                            {"plain_text": "段落"},
                            {"plain_text": "段落"},
                        ],
                    },
                )
                self.assertEqual(len(split_result["created_block_ids"]), 2)

                latest_graph = graph_module.get_doc_blocks_graph("default", "doc-batch-1")
                self.assertIsNotNone(latest_graph)
                latest_node_map = {
                    node["block_uid"]: node
                    for node in latest_graph["nodes"]
                    if int(node.get("is_active", 1) or 0) != 0
                }
                self.assertNotIn("doc-batch-1:0:3", latest_node_map)
                self.assertEqual(latest_node_map["doc-batch-1:0:2"]["page_idx"], 0)
                self.assertEqual(latest_node_map["doc-batch-1:0:2"]["parent_uid"], "doc-batch-1:0:1")
                self.assertEqual(latest_node_map[split_result["created_block_ids"][0]]["page_idx"], 0)
                self.assertEqual(latest_node_map[split_result["created_block_ids"][1]]["page_idx"], 0)
                self.assertEqual(latest_node_map["doc-batch-1:0:2"]["plain_text"], "段落一")
                self.assertEqual(latest_node_map[split_result["created_block_ids"][0]]["plain_text"], "段落")
                self.assertEqual(latest_node_map[split_result["created_block_ids"][1]]["plain_text"], "段落")
                self.assertEqual(latest_node_map[split_result["created_block_ids"][0]]["block_type"], "paragraph")
                self.assertEqual(latest_node_map[split_result["created_block_ids"][1]]["block_type"], "paragraph")
                self.assertIsNone(latest_node_map[split_result["created_block_ids"][0]].get("image_path"))
                self.assertIsNone(latest_node_map[split_result["created_block_ids"][1]].get("image_path"))
                self.assertEqual(latest_node_map[split_result["created_block_ids"][0]].get("content_json"), {})
                self.assertEqual(latest_node_map[split_result["created_block_ids"][1]].get("content_json"), {})
                ordered_block_uids = [
                    node["block_uid"]
                    for node in latest_graph["nodes"]
                    if int(node.get("is_active", 1) or 0) != 0
                ]
                split_anchor_index = ordered_block_uids.index("doc-batch-1:0:2")
                self.assertEqual(
                    ordered_block_uids[split_anchor_index:split_anchor_index + 3],
                    ["doc-batch-1:0:2", *split_result["created_block_ids"]],
                )

                projected_rows = isolated_service.index_store.query_doc_blocks("doc-batch-1", limit=20)
                projected_uids = {row["block_uid"] for row in projected_rows}
                self.assertIn(split_result["created_block_ids"][0], projected_uids)
                self.assertIn(split_result["created_block_ids"][1], projected_uids)
                self.assertNotIn("doc-batch-1:0:3", projected_uids)

                projected_segments = isolated_service.list_document_segments("doc-batch-1", "doc_blocks_graph_v1")
                segment_uids = {item["meta"]["block_uid"] for item in projected_segments}
                self.assertIn(split_result["created_block_ids"][0], segment_uids)
                self.assertIn(split_result["created_block_ids"][1], segment_uids)

                delete_result = batch_operate_doc_blocks(
                    "default",
                    "doc-batch-1",
                    "delete",
                    {
                        "operation": "delete",
                        "blockIds": [split_result["created_block_ids"][0]],
                    },
                )
                self.assertEqual(delete_result["removed_block_ids"], [split_result["created_block_ids"][0]])

                deleted_graph = graph_module.get_doc_blocks_graph("default", "doc-batch-1")
                self.assertIsNotNone(deleted_graph)
                deleted_node_map = {
                    node["block_uid"]: node
                    for node in deleted_graph["nodes"]
                    if int(node.get("is_active", 1) or 0) != 0
                }
                self.assertNotIn(split_result["created_block_ids"][0], deleted_node_map)

                undo_delete_result = undo_last_doc_block_merge("default", "doc-batch-1")
                self.assertIn(split_result["created_block_ids"][0], undo_delete_result["restored_block_ids"])

                restored_after_delete_graph = graph_module.get_doc_blocks_graph("default", "doc-batch-1")
                self.assertIsNotNone(restored_after_delete_graph)
                restored_after_delete_node_map = {
                    node["block_uid"]: node
                    for node in restored_after_delete_graph["nodes"]
                    if int(node.get("is_active", 1) or 0) != 0
                }
                self.assertIn(split_result["created_block_ids"][0], restored_after_delete_node_map)

                undo_split_result = undo_last_doc_block_merge("default", "doc-batch-1")
                self.assertTrue(undo_split_result["restored_block_ids"])

                restored_merge_graph = graph_module.get_doc_blocks_graph("default", "doc-batch-1")
                self.assertIsNotNone(restored_merge_graph)
                restored_merge_node_map = {
                    node["block_uid"]: node
                    for node in restored_merge_graph["nodes"]
                    if int(node.get("is_active", 1) or 0) != 0
                }
                self.assertNotIn("doc-batch-1:0:3", restored_merge_node_map)
                self.assertEqual(restored_merge_node_map["doc-batch-1:0:2"]["image_path"], "assets/img-a.png")

                undo_merge_result = undo_last_doc_block_merge("default", "doc-batch-1")
                self.assertTrue(undo_merge_result["restored_block_ids"])

                restored_graph = graph_module.get_doc_blocks_graph("default", "doc-batch-1")
                self.assertIsNotNone(restored_graph)
                restored_node_map = {
                    node["block_uid"]: node
                    for node in restored_graph["nodes"]
                    if int(node.get("is_active", 1) or 0) != 0
                }
                self.assertIn("doc-batch-1:0:3", restored_node_map)
                self.assertEqual(restored_node_map["doc-batch-1:0:2"]["image_path"], "assets/img-a.png")
                self.assertEqual(restored_node_map["doc-batch-1:0:3"]["image_path"], "assets/img-b.png")
            finally:
                docs_service_module.docs_service = previous_service
                fs_module.file_storage = previous_storage
                if previous_base_dir is None:
                    os.environ.pop("KNOWLEDGE_BASE_DIR", None)
                else:
                    os.environ["KNOWLEDGE_BASE_DIR"] = previous_base_dir
                del isolated_service
                gc.collect()

    def test_batch_relevel_blocks_and_undo(self):
        """测试批量升降标题层级会整体重算父级并支持撤回。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "knowledge_meta.sqlite"
            isolated_service = IsolatedDocsService(db_path)
            isolated_storage = FileStorage(base_dir=temp_dir)
            previous_base_dir = os.environ.get("KNOWLEDGE_BASE_DIR")
            os.environ["KNOWLEDGE_BASE_DIR"] = temp_dir
            previous_service = docs_service_module.docs_service
            previous_storage = fs_module.file_storage
            docs_service_module.docs_service = isolated_service
            fs_module.file_storage = isolated_storage
            try:
                node = KnowledgeNode(
                    id="doc-batch-relevel-1",
                    title="批量层级调整测试",
                    type="document",
                    library_id="default",
                    status="completed"
                )
                isolated_service.create_node(node)
                graph_data = {
                    "doc_id": "doc-batch-relevel-1",
                    "doc_name": "批量层级调整测试",
                    "nodes": [
                        {
                            "id": "doc-batch-relevel-1:0:1",
                            "block_uid": "doc-batch-relevel-1:0:1",
                            "block_type": "title",
                            "page_idx": 0,
                            "block_seq": 1,
                            "plain_text": "第一",
                            "bbox": [0.0, 0.0, 1.0, 0.1],
                            "bbox_source": "layout",
                            "derived_level": 1,
                            "title_path": "doc-batch-relevel-1:0:1",
                            "parent_uid": None,
                            "derived_by": "rule",
                            "confidence": 0.99,
                            "content_json": {},
                        },
                        {
                            "id": "doc-batch-relevel-1:0:2",
                            "block_uid": "doc-batch-relevel-1:0:2",
                            "block_type": "title",
                            "page_idx": 0,
                            "block_seq": 2,
                            "plain_text": "第二",
                            "bbox": [0.0, 0.1, 1.0, 0.2],
                            "bbox_source": "layout",
                            "derived_level": 1,
                            "title_path": "doc-batch-relevel-1:0:2",
                            "parent_uid": None,
                            "derived_by": "rule",
                            "confidence": 0.99,
                            "content_json": {},
                        },
                        {
                            "id": "doc-batch-relevel-1:0:3",
                            "block_uid": "doc-batch-relevel-1:0:3",
                            "block_type": "title",
                            "page_idx": 0,
                            "block_seq": 3,
                            "plain_text": "第二第一",
                            "bbox": [0.0, 0.2, 1.0, 0.3],
                            "bbox_source": "layout",
                            "derived_level": 1,
                            "title_path": "doc-batch-relevel-1:0:3",
                            "parent_uid": None,
                            "derived_by": "rule",
                            "confidence": 0.95,
                            "content_json": {},
                        },
                        {
                            "id": "doc-batch-relevel-1:0:4",
                            "block_uid": "doc-batch-relevel-1:0:4",
                            "block_type": "title",
                            "page_idx": 0,
                            "block_seq": 4,
                            "plain_text": "第二第一第一",
                            "bbox": [0.0, 0.3, 1.0, 0.4],
                            "bbox_source": "layout",
                            "derived_level": 2,
                            "title_path": "doc-batch-relevel-1:0:3>doc-batch-relevel-1:0:4",
                            "parent_uid": "doc-batch-relevel-1:0:3",
                            "derived_by": "rule",
                            "confidence": 0.92,
                            "content_json": {},
                        },
                    ],
                    "edges": [],
                    "stats": {
                        "base_rows": [],
                        "derived_rows": [],
                        "index_rows": [],
                    },
                }
                graph_module._rebuild_graph_projection(graph_data)
                _write_graph_files("default", "doc-batch-relevel-1", graph_data, temp_dir)

                relevel_result = batch_operate_doc_blocks(
                    "default",
                    "doc-batch-relevel-1",
                    "relevel",
                    {
                        "operation": "relevel",
                        "blockIds": ["doc-batch-relevel-1:0:3", "doc-batch-relevel-1:0:4"],
                        "levelDelta": 1,
                    },
                )
                self.assertEqual(
                    relevel_result["updated_block_ids"],
                    ["doc-batch-relevel-1:0:3", "doc-batch-relevel-1:0:4"],
                )

                latest_graph = graph_module.get_doc_blocks_graph("default", "doc-batch-relevel-1")
                self.assertIsNotNone(latest_graph)
                latest_node_map = {
                    node["block_uid"]: node
                    for node in latest_graph["nodes"]
                    if int(node.get("is_active", 1) or 0) != 0
                }
                self.assertEqual(latest_node_map["doc-batch-relevel-1:0:3"]["derived_level"], 2)
                self.assertEqual(latest_node_map["doc-batch-relevel-1:0:3"]["parent_uid"], "doc-batch-relevel-1:0:2")
                self.assertEqual(latest_node_map["doc-batch-relevel-1:0:4"]["derived_level"], 3)
                self.assertEqual(latest_node_map["doc-batch-relevel-1:0:4"]["parent_uid"], "doc-batch-relevel-1:0:3")

                projected_segments = isolated_service.list_document_segments("doc-batch-relevel-1", "doc_blocks_graph_v1")
                projected_segment_map = {
                    item["meta"]["block_uid"]: item["meta"]
                    for item in projected_segments
                }
                self.assertEqual(projected_segment_map["doc-batch-relevel-1:0:3"]["derived_level"], 2)
                self.assertEqual(projected_segment_map["doc-batch-relevel-1:0:3"]["parent_uid"], "doc-batch-relevel-1:0:2")
                self.assertEqual(projected_segment_map["doc-batch-relevel-1:0:4"]["derived_level"], 3)
                self.assertEqual(projected_segment_map["doc-batch-relevel-1:0:4"]["parent_uid"], "doc-batch-relevel-1:0:3")

                undo_result = undo_last_doc_block_merge("default", "doc-batch-relevel-1")
                self.assertIn("doc-batch-relevel-1:0:3", undo_result["restored_block_ids"])

                restored_graph = graph_module.get_doc_blocks_graph("default", "doc-batch-relevel-1")
                self.assertIsNotNone(restored_graph)
                restored_node_map = {
                    node["block_uid"]: node
                    for node in restored_graph["nodes"]
                    if int(node.get("is_active", 1) or 0) != 0
                }
                self.assertEqual(restored_node_map["doc-batch-relevel-1:0:3"]["derived_level"], 1)
                self.assertIsNone(restored_node_map["doc-batch-relevel-1:0:3"]["parent_uid"])
                self.assertEqual(restored_node_map["doc-batch-relevel-1:0:4"]["derived_level"], 2)
                self.assertEqual(restored_node_map["doc-batch-relevel-1:0:4"]["parent_uid"], "doc-batch-relevel-1:0:3")
            finally:
                docs_service_module.docs_service = previous_service
                fs_module.file_storage = previous_storage
                if previous_base_dir is None:
                    os.environ.pop("KNOWLEDGE_BASE_DIR", None)
                else:
                    os.environ["KNOWLEDGE_BASE_DIR"] = previous_base_dir
                del isolated_service
                gc.collect()

    def test_batch_set_same_target_level_for_multiple_blocks(self):
        """测试多选多个节点后可一次性直接设置为同一层级。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "knowledge_meta.sqlite"
            isolated_service = IsolatedDocsService(db_path)
            isolated_storage = FileStorage(base_dir=temp_dir)
            previous_base_dir = os.environ.get("KNOWLEDGE_BASE_DIR")
            os.environ["KNOWLEDGE_BASE_DIR"] = temp_dir
            previous_service = docs_service_module.docs_service
            previous_storage = fs_module.file_storage
            docs_service_module.docs_service = isolated_service
            fs_module.file_storage = isolated_storage
            try:
                node = KnowledgeNode(
                    id="doc-batch-target-level-1",
                    title="批量绝对层级设置测试",
                    type="document",
                    library_id="default",
                    status="completed"
                )
                isolated_service.create_node(node)
                graph_data = {
                    "doc_id": "doc-batch-target-level-1",
                    "doc_name": "批量绝对层级设置测试",
                    "nodes": [
                        {
                            "id": "doc-batch-target-level-1:0:1",
                            "block_uid": "doc-batch-target-level-1:0:1",
                            "block_type": "title",
                            "page_idx": 0,
                            "block_seq": 1,
                            "plain_text": "第一",
                            "bbox": [0.0, 0.0, 1.0, 0.1],
                            "bbox_source": "layout",
                            "derived_level": 1,
                            "title_path": "doc-batch-target-level-1:0:1",
                            "parent_uid": None,
                            "derived_by": "rule",
                            "confidence": 0.99,
                            "content_json": {},
                        },
                        {
                            "id": "doc-batch-target-level-1:0:2",
                            "block_uid": "doc-batch-target-level-1:0:2",
                            "block_type": "title",
                            "page_idx": 0,
                            "block_seq": 2,
                            "plain_text": "第二",
                            "bbox": [0.0, 0.1, 1.0, 0.2],
                            "bbox_source": "layout",
                            "derived_level": 1,
                            "title_path": "doc-batch-target-level-1:0:2",
                            "parent_uid": None,
                            "derived_by": "rule",
                            "confidence": 0.99,
                            "content_json": {},
                        },
                        {
                            "id": "doc-batch-target-level-1:0:3",
                            "block_uid": "doc-batch-target-level-1:0:3",
                            "block_type": "title",
                            "page_idx": 0,
                            "block_seq": 3,
                            "plain_text": "2.1",
                            "bbox": [0.0, 0.2, 1.0, 0.3],
                            "bbox_source": "layout",
                            "derived_level": 2,
                            "title_path": "doc-batch-target-level-1:0:2>doc-batch-target-level-1:0:3",
                            "parent_uid": "doc-batch-target-level-1:0:2",
                            "derived_by": "rule",
                            "confidence": 0.96,
                            "content_json": {},
                        },
                        {
                            "id": "doc-batch-target-level-1:0:4",
                            "block_uid": "doc-batch-target-level-1:0:4",
                            "block_type": "title",
                            "page_idx": 0,
                            "block_seq": 4,
                            "plain_text": "2.2",
                            "bbox": [0.0, 0.3, 1.0, 0.4],
                            "bbox_source": "layout",
                            "derived_level": 1,
                            "title_path": "doc-batch-target-level-1:0:4",
                            "parent_uid": None,
                            "derived_by": "rule",
                            "confidence": 0.96,
                            "content_json": {},
                        },
                        {
                            "id": "doc-batch-target-level-1:0:5",
                            "block_uid": "doc-batch-target-level-1:0:5",
                            "block_type": "title",
                            "page_idx": 0,
                            "block_seq": 5,
                            "plain_text": "2.3",
                            "bbox": [0.0, 0.4, 1.0, 0.5],
                            "bbox_source": "layout",
                            "derived_level": 1,
                            "title_path": "doc-batch-target-level-1:0:5",
                            "parent_uid": None,
                            "derived_by": "rule",
                            "confidence": 0.96,
                            "content_json": {},
                        },
                        {
                            "id": "doc-batch-target-level-1:0:6",
                            "block_uid": "doc-batch-target-level-1:0:6",
                            "block_type": "title",
                            "page_idx": 0,
                            "block_seq": 6,
                            "plain_text": "2.4",
                            "bbox": [0.0, 0.5, 1.0, 0.6],
                            "bbox_source": "layout",
                            "derived_level": 1,
                            "title_path": "doc-batch-target-level-1:0:6",
                            "parent_uid": None,
                            "derived_by": "rule",
                            "confidence": 0.96,
                            "content_json": {},
                        },
                    ],
                    "edges": [],
                    "stats": {
                        "base_rows": [],
                        "derived_rows": [],
                        "index_rows": [],
                    },
                }
                graph_module._rebuild_graph_projection(graph_data)
                _write_graph_files("default", "doc-batch-target-level-1", graph_data, temp_dir)

                result = batch_operate_doc_blocks(
                    "default",
                    "doc-batch-target-level-1",
                    "relevel",
                    {
                        "operation": "relevel",
                        "blockIds": [
                            "doc-batch-target-level-1:0:3",
                            "doc-batch-target-level-1:0:4",
                            "doc-batch-target-level-1:0:5",
                            "doc-batch-target-level-1:0:6",
                        ],
                        "targetLevel": 3,
                    },
                )
                self.assertEqual(
                    result["updated_block_ids"],
                    [
                        "doc-batch-target-level-1:0:3",
                        "doc-batch-target-level-1:0:4",
                        "doc-batch-target-level-1:0:5",
                        "doc-batch-target-level-1:0:6",
                    ],
                )

                latest_graph = graph_module.get_doc_blocks_graph("default", "doc-batch-target-level-1")
                self.assertIsNotNone(latest_graph)
                latest_node_map = {
                    node["block_uid"]: node
                    for node in latest_graph["nodes"]
                    if int(node.get("is_active", 1) or 0) != 0
                }
                for block_uid in [
                    "doc-batch-target-level-1:0:3",
                    "doc-batch-target-level-1:0:4",
                    "doc-batch-target-level-1:0:5",
                    "doc-batch-target-level-1:0:6",
                ]:
                    self.assertEqual(latest_node_map[block_uid]["derived_level"], 3)
                    self.assertIsNone(latest_node_map[block_uid]["parent_uid"])
            finally:
                docs_service_module.docs_service = previous_service
                fs_module.file_storage = previous_storage
                if previous_base_dir is None:
                    os.environ.pop("KNOWLEDGE_BASE_DIR", None)
                else:
                    os.environ["KNOWLEDGE_BASE_DIR"] = previous_base_dir
                del isolated_service
                gc.collect()


if __name__ == "__main__":
    unittest.main()
