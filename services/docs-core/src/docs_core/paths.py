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
KNOWLEDGE_GRAPH_DB_NAME = "graph.sqlite"


def _knowledge_base(base_dir: Path | str | None) -> Path:
    """统一解析知识库根：显式 base_dir 优先，否则走全局 KNOWLEDGE_BASE_DIR。"""
    if base_dir is not None:
        return Path(base_dir)
    return resolve_knowledge_base_dir()


# ---- 仓库与数据根 ----


def resolve_repo_root() -> Path:
    """解析主仓库根目录。

    解析顺序（2026-10-07 独立发版改造）：``ANGINEER_REPO_ROOT`` 显式指定 > 向上探测仓库标记
    （同时含 ``apps/`` / ``services/`` / ``package.json``）。两者都拿不到就抛错——
    **不再回落到「往上数第 6 层」**：那个近似只在仓库树里碰巧成立，装成 wheel 后必然指向
    site-packages 附近的错误目录，且要等写文件时才暴露。独立部署请显式给
    ``ANGINEER_REPO_ROOT``（仓库树外的根），或直接给数据根 ``KNOWLEDGE_BASE_DIR`` /
    ``ANGINEER_DATA_ROOT``（``resolve_knowledge_base_dir`` 会优先用它们，不再走本函数）。
    """
    explicit = os.getenv("ANGINEER_REPO_ROOT", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    current_file = Path(__file__).resolve()
    for candidate in current_file.parents:
        if (
            (candidate / "apps").exists()
            and (candidate / "services").exists()
            and (candidate / "package.json").exists()
        ):
            return candidate
    raise RuntimeError(
        "无法定位主仓库根目录：未设置 ANGINEER_REPO_ROOT，向上也找不到同时含 apps/、services/、"
        "package.json 的目录（独立安装的 wheel 里没有仓库树）。请设置 ANGINEER_REPO_ROOT，"
        "或直接指定数据根 KNOWLEDGE_BASE_DIR / ANGINEER_DATA_ROOT。"
    )


def resolve_knowledge_base_dir() -> Path:
    """解析知识库数据根目录（``KNOWLEDGE_BASE_DIR`` > ``ANGINEER_DATA_ROOT``/knowledge > repo/data/knowledge）。

    2026-10 data/ 三域归位（plan-kb-split-groups 阶段二）：目录由 ``knowledge_base``
    改名为 ``knowledge``（生产知识域）；``KNOWLEDGE_BASE_DIR`` 变量名保留不动。
    ``ANGINEER_DATA_ROOT`` 与 library_registry 共用同一数据根口径，保证「组文件回退
    默认单文件」解析出的路径与本函数一致（测试隔离依赖这一点，2026-10-03 实踩）。
    """
    env_override = os.getenv("KNOWLEDGE_BASE_DIR", "").strip()
    if env_override:
        return Path(env_override).expanduser()
    data_root = os.getenv("ANGINEER_DATA_ROOT", "").strip()
    if data_root:
        return Path(data_root).expanduser() / "knowledge"
    return resolve_repo_root() / "data" / "knowledge"


def resolve_knowledge_meta_db_path() -> Path:
    return resolve_knowledge_base_dir() / KNOWLEDGE_META_DB_NAME


def resolve_knowledge_index_db_path() -> Path:
    return resolve_knowledge_base_dir() / KNOWLEDGE_INDEX_DB_NAME


def resolve_graph_db_path() -> Path:
    """知识图谱库路径：<data 根>/knowledge/graph.sqlite（收编进知识域，2026-10 起）。"""
    return resolve_knowledge_base_dir() / KNOWLEDGE_GRAPH_DB_NAME


def to_data_relative(path: Path | str) -> str:
    """data 根之下的绝对路径收敛为相对 data 根的 POSIX 相对路径；库外路径原样返回字符串。

    写入 nodes.file_path 用（plan-standards-kb-corpus-package Stage A）：语料包
    export→import 跨环境时相对路径零改写；data 根口径与 library_registry 共用。
    """
    from .library_registry import resolve_data_root  # 懒加载：registry 顶层 import paths

    p = Path(path)
    root = resolve_data_root()
    try:
        return p.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        # 原样返回，绝不经过 Path 重塑（Windows 上 Path 会把 / 改写为 \，幂等性依赖此处）
        return path if isinstance(path, str) else str(p)


def resolve_node_file_path(value: str | None) -> Path | None:
    """nodes.file_path 统一展开：相对值按 data 根展开；绝对/旧值原样；空返回 None。"""
    from .library_registry import resolve_data_root

    if not value:
        return None
    p = Path(value)
    if p.is_absolute() or (len(value) > 1 and value[0].isalpha() and value[1] == ":"):
        return p
    return resolve_data_root() / p


def resolve_chroma_persist_dir(base_path: Path | None = None) -> Path:
    """解析向量持久化目录（默认 knowledge_base/vectorstore/chroma，测试可传 base_path）。"""
    if base_path is not None:
        return Path(base_path).resolve().parent / "chroma"
    return resolve_knowledge_base_dir() / "vectorstore" / "chroma"


# ---- 文档目录布局 ----


def library_root(library_id: str, base_dir: Path | str | None = None) -> Path:
    """库目录根：显式 base_dir 优先（测试用）；默认经注册表按组路由
    （plan-kb-split-groups：生产组 → knowledge/libraries，评测组 → evals/corpora/libraries，
    组目标目录存在即生效，否则回落知识库根 libraries/——跨搬迁窗口安全）。"""
    if base_dir is None:
        from . import library_registry  # 懒加载避免循环导入（registry 顶层 import paths）

        return library_registry.resolve_libraries_dir(library_id) / library_id
    return Path(base_dir) / "libraries" / library_id


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
    "resolve_node_file_path",
    "to_data_relative",
]
