"""nodes.file_path 相对化改造的地基：to_data_relative / resolve_node_file_path。

背景（plan-standards-kb-corpus-package Stage A）：file_path 现存上传机的绝对路径，
跨环境（语料包 export→生产 import）必然过期成「源文件不存在」雷。本任务把
data 根之下的路径收敛为相对 data 根的 POSIX 相对路径；库外/旧绝对值原样透传，
读取一律经 resolve_node_file_path 展开（相对/绝对/旧三态兼容）。
"""
from pathlib import Path

from docs_core import paths


def test_to_data_relative_posix_under_root(tmp_path, monkeypatch):
    monkeypatch.setenv("ANGINEER_DATA_ROOT", str(tmp_path))
    p = tmp_path / "knowledge" / "libraries" / "lib-x" / "documents" / "d1" / "source" / "a.pdf"
    got = paths.to_data_relative(p)
    assert "\\" not in got
    assert got == "knowledge/libraries/lib-x/documents/d1/source/a.pdf"


def test_to_data_relative_outside_root_passthrough(tmp_path, monkeypatch):
    monkeypatch.setenv("ANGINEER_DATA_ROOT", str(tmp_path))
    outside = tmp_path.parent / "elsewhere.pdf"
    assert paths.to_data_relative(outside) == str(outside)


def test_to_data_relative_is_idempotent_on_relative_input():
    """幂等：已是相对 POSIX 形态的值必须逐字符原样——清洗脚本可重入依赖此处。
    （Windows 上 str(Path("a/b")) 会重塑成反斜杠形态，透传不许经过 Path。）"""
    rel = "knowledge/libraries/lib-x/documents/d1/source/a.pdf"
    assert paths.to_data_relative(rel) == rel


def test_resolve_node_file_path_relative_and_legacy(tmp_path, monkeypatch):
    monkeypatch.setenv("ANGINEER_DATA_ROOT", str(tmp_path))
    rel = "knowledge/libraries/lib-x/documents/d1/source/a.pdf"
    assert paths.resolve_node_file_path(rel) == tmp_path / rel
    # 旧绝对行原样（含 Windows 盘符形态，source_prep 兜底契约依赖它不抛错）
    legacy = str(tmp_path / "abs.pdf")
    assert paths.resolve_node_file_path(legacy) == Path(legacy)
    legacy_win = r"D:\AI\AnGIneer\data\knowledge\x.pdf"
    assert paths.resolve_node_file_path(legacy_win) == Path(legacy_win)
    assert paths.resolve_node_file_path("") is None
    assert paths.resolve_node_file_path(None) is None


def test_register_document_stores_relative(tmp_path, monkeypatch):
    """写入口定版：data 根之下的 file_path 落库必须是相对路径（跨环境零改写的前提）。"""
    monkeypatch.setenv("ANGINEER_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("DOCS_VECTORSTORE_PROVIDER", "sqlite")
    from docs_core.docs_service import DocsService

    svc = DocsService()
    lib = "lib-rel-test"
    svc.create_library(lib, "相对路径测试库", "")
    src = tmp_path / "knowledge" / "libraries" / lib / "documents" / "d1" / "source" / "a.pdf"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"x")
    svc.register_document(lib, str(src), doc_id="d1")
    stored = svc.get_node("d1")
    assert stored.file_path == f"knowledge/libraries/{lib}/documents/d1/source/a.pdf"


def test_ensure_source_file_accepts_relative(tmp_path, monkeypatch):
    """读点契约：file_path 为相对 data 根路径时，source_prep 必须能按候选拷入规范目录。

    候选故意放在规范 source 目录之外——若 resolver 缺位，Path(rel).exists() 按当前
    cwd 解析恒 False，会走不到候选拷贝分支。
    """
    monkeypatch.setenv("ANGINEER_DATA_ROOT", str(tmp_path))
    from docs_core.step01_source_prep.source_prep import _ensure_source_file

    rel = "knowledge/staging/a.pdf"
    src = tmp_path / rel
    src.parent.mkdir(parents=True)
    src.write_bytes(b"x")
    got = _ensure_source_file("lib-x", "d1", file_path=rel, base_dir=str(tmp_path / "knowledge"))
    assert got and Path(got).name == "a.pdf"
    assert Path(got).read_bytes() == b"x"
