"""文档布局与数据根路径解析（纯路径计算，无 IO 副作用）。

本模块集中定义"知识库/文档在磁盘上的位置"这一布局知识：

- 数据根：``resolve_repo_root`` / ``resolve_knowledge_base_dir`` /
  ``resolve_knowledge_meta_db_path`` / ``resolve_knowledge_index_db_path`` /
  ``resolve_graph_db_path`` / ``resolve_chroma_persist_dir``
- 文档目录：``library_root`` / ``get_doc_root`` / ``get_source_dir`` /
  ``get_parsed_dir`` / ``get_edited_dir`` / ``get_raw_dir`` /
  ``get_mineru_raw_dir`` / ``get_popo_dir`` 及具体文件路径
- 输入探测：``resolve_structured_input_dir`` / ``resolve_structure_input_dir``
  （只读 exists 判断，不写盘）

约定：本模块所有函数只返回 :class:`pathlib.Path`，**不创建目录、不写文件**。
需要写文件的一方自行 ``path.parent.mkdir(parents=True, exist_ok=True)``。
"""

import os
from pathlib import Path

KNOWLEDGE_META_DB_NAME = "knowledge_meta.sqlite"
KNOWLEDGE_INDEX_DB_NAME = "knowledge_index.sqlite"
KNOWLEDGE_GRAPH_DB_NAME = "knowledge_graph.sqlite"


def _knowledge_base(base_dir: Path | str | None) -> Path:
    """统一解析知识库根：显式 base_dir 优先，否则走全局 KNOWLEDGE_BASE_DIR。"""
    if base_dir is not None:
        return Path(base_dir)
    return resolve_knowledge_base_dir()


# ---- 仓库与数据根 ----


def resolve_repo_root() -> Path:
    """解析 monorepo 根目录（向上找 apps/services/package.json 并存）。"""
    current_file = Path(__file__).resolve()
    for candidate in current_file.parents:
        if (
            (candidate / "apps").exists()
            and (candidate / "services").exists()
            and (candidate / "package.json").exists()
        ):
            return candidate
    return current_file.parents[6]


def resolve_knowledge_base_dir() -> Path:
    """解析知识库数据根目录（``KNOWLEDGE_BASE_DIR`` 可覆盖，默认 repo/data/knowledge_base）。"""
    env_override = os.getenv("KNOWLEDGE_BASE_DIR", "").strip()
    if env_override:
        return Path(env_override).expanduser()
    return resolve_repo_root() / "data" / "knowledge_base"


def resolve_knowledge_meta_db_path() -> Path:
    return resolve_knowledge_base_dir() / KNOWLEDGE_META_DB_NAME


def resolve_knowledge_index_db_path() -> Path:
    return resolve_knowledge_base_dir() / KNOWLEDGE_INDEX_DB_NAME


def resolve_graph_db_path() -> Path:
    """默认知识图谱库路径：repo/data/knowledge_graph.sqlite。"""
    return resolve_repo_root() / "data" / KNOWLEDGE_GRAPH_DB_NAME


def resolve_chroma_persist_dir(base_path: Path | None = None) -> Path:
    """解析向量持久化目录（默认 knowledge_base/vectorstore/chroma，测试可传 base_path）。"""
    if base_path is not None:
        return Path(base_path).resolve().parent / "chroma"
    return resolve_knowledge_base_dir() / "vectorstore" / "chroma"


# ---- 文档目录布局 ----


def library_root(library_id: str, base_dir: Path | str | None = None) -> Path:
    return _knowledge_base(base_dir) / "libraries" / library_id


def get_doc_root(library_id: str, doc_id: str, base_dir: Path | str | None = None) -> Path:
    return library_root(library_id, base_dir=base_dir) / "documents" / doc_id


def get_source_dir(library_id: str, doc_id: str, base_dir: Path | str | None = None) -> Path:
    return get_doc_root(library_id, doc_id, base_dir=base_dir) / "source"


def get_parsed_dir(library_id: str, doc_id: str, base_dir: Path | str | None = None) -> Path:
    return get_doc_root(library_id, doc_id, base_dir=base_dir) / "parsed"


def get_edited_dir(library_id: str, doc_id: str, base_dir: Path | str | None = None) -> Path:
    return get_doc_root(library_id, doc_id, base_dir=base_dir) / "edited"


def get_raw_dir(library_id: str, doc_id: str, base_dir: Path | str | None = None) -> Path:
    return get_parsed_dir(library_id, doc_id, base_dir=base_dir) / "raw"


def get_mineru_raw_dir(library_id: str, doc_id: str, base_dir: Path | str | None = None) -> Path:
    return get_parsed_dir(library_id, doc_id, base_dir=base_dir) / "mineru_raw"


def get_popo_dir(library_id: str, doc_id: str, base_dir: Path | str | None = None) -> Path:
    return get_parsed_dir(library_id, doc_id, base_dir=base_dir) / "popo"


def get_graph_jsonl_path(library_id: str, doc_id: str, base_dir: Path | str | None = None) -> Path:
    return get_parsed_dir(library_id, doc_id, base_dir=base_dir) / "doc_blocks_graph.jsonl"


def get_graph_meta_path(library_id: str, doc_id: str, base_dir: Path | str | None = None) -> Path:
    return get_parsed_dir(library_id, doc_id, base_dir=base_dir) / "doc_blocks_graph_meta.json"


def get_parsed_markdown_path(library_id: str, doc_id: str, base_dir: Path | str | None = None) -> Path:
    return get_parsed_dir(library_id, doc_id, base_dir=base_dir) / "content.md"


def get_edited_markdown_path(library_id: str, doc_id: str, base_dir: Path | str | None = None) -> Path:
    return get_edited_dir(library_id, doc_id, base_dir=base_dir) / "current.md"


def get_mineru_blocks_path(library_id: str, doc_id: str, base_dir: Path | str | None = None) -> Path:
    return get_parsed_dir(library_id, doc_id, base_dir=base_dir) / "mineru_blocks.json"


def get_popo_enriched_blocks_path(library_id: str, doc_id: str, base_dir: Path | str | None = None) -> Path:
    return get_popo_dir(library_id, doc_id, base_dir=base_dir) / "enriched_blocks.json"


def get_popo_document_tree_path(library_id: str, doc_id: str, base_dir: Path | str | None = None) -> Path:
    return get_popo_dir(library_id, doc_id, base_dir=base_dir) / "document_tree.json"


# ---- 输入目录探测（只读 exists 判断，不写盘） ----


def resolve_structured_input_dir(raw_dir: Path) -> Path:
    """解析结构化主链应优先读取的原始目录（content_list_v2 > content_list > layout+model）。"""
    if (raw_dir / "content_list_v2.json").exists():
        return raw_dir
    if (raw_dir / "content_list.json").exists():
        return raw_dir
    if (raw_dir / "layout.json").exists() and (raw_dir / "model.json").exists():
        return raw_dir
    raise ValueError(f"文档尚无可用解析输入: {raw_dir}")


def resolve_structure_input_dir(library_id: str, doc_id: str, base_dir: Path | str | None = None) -> Path:
    """解析 structure 阶段输入目录（优先 mineru_raw，其次 parsed）。"""
    mineru_raw_dir = get_mineru_raw_dir(library_id, doc_id, base_dir=base_dir)
    if mineru_raw_dir.exists():
        return resolve_structured_input_dir(mineru_raw_dir)
    return resolve_structured_input_dir(get_parsed_dir(library_id, doc_id, base_dir=base_dir))


__all__ = [
    "KNOWLEDGE_GRAPH_DB_NAME",
    "KNOWLEDGE_INDEX_DB_NAME",
    "KNOWLEDGE_META_DB_NAME",
    "get_doc_root",
    "get_edited_dir",
    "get_edited_markdown_path",
    "get_graph_jsonl_path",
    "get_graph_meta_path",
    "get_mineru_blocks_path",
    "get_mineru_raw_dir",
    "get_parsed_dir",
    "get_parsed_markdown_path",
    "get_popo_dir",
    "get_popo_document_tree_path",
    "get_popo_enriched_blocks_path",
    "get_raw_dir",
    "get_source_dir",
    "library_root",
    "resolve_structure_input_dir",
    "resolve_chroma_persist_dir",
    "resolve_graph_db_path",
    "resolve_knowledge_base_dir",
    "resolve_knowledge_index_db_path",
    "resolve_knowledge_meta_db_path",
    "resolve_repo_root",
    "resolve_structured_input_dir",
]
