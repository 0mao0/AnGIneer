"""源文件路径兜底契约：file_path 失效（历史批量导入写的是另一台机器的绝对路径）时，
规范 source 目录里的原件必须仍被解析管线与 API 层认出来。

生产实况：nodes.file_path 里 183 条是开发机路径 D:\\AI\\AnGIneer\\...，
Linux 容器上 Path(...).exists() 恒为 False —— 「开始解析」曾因此在入口 404，
而文件其实就躺在 libraries/<lib>/documents/<doc>/source/ 下。
"""
from pathlib import Path

from docs_core.step01_source_prep.source_prep import prepare_source, resolve_source_file

LIB = "lib-b07ed174"
DOC = "v1-dba3751d9acb"
# 生产实况里的失效路径形如 D:\AI\AnGIneer\data\knowledge_base\libraries\...，
# 但那份库在开发机上真实存在，用它做测试会在 Windows 上走不到"失效"分支。
# 故换成一个不存在的根：形态不变（带盘符 + 反斜杠），任何机器上都解析不到。
FOREIGN_PATH = rf"D:\__missing_machine__\libraries\{LIB}\documents\{DOC}\source\2404.14603v2.pdf"


def _make_doc_dir(tmp_path, monkeypatch, files: list[str]) -> Path:
    monkeypatch.setenv("KNOWLEDGE_BASE_DIR", str(tmp_path))
    source_dir = tmp_path / "libraries" / LIB / "documents" / DOC / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    for name in files:
        (source_dir / name).write_bytes(b"%PDF-1.5\n")
    return source_dir


def test_foreign_path_fixture_is_really_unresolvable() -> None:
    """护栏：FOREIGN_PATH 若在某台机器上真存在，下面几个"失效路径"用例就失去意义。"""
    assert not Path(FOREIGN_PATH).exists()


def test_resolve_source_file_reads_canonical_dir(tmp_path, monkeypatch) -> None:
    source_dir = _make_doc_dir(tmp_path, monkeypatch, ["2404.14603v2.pdf"])

    assert resolve_source_file(LIB, DOC) == str(source_dir / "2404.14603v2.pdf")


def test_resolve_source_file_is_read_only_when_dir_missing(tmp_path, monkeypatch) -> None:
    """缺目录必须返回 None 且不建目录（路由兜底失败要能干净地 404）。"""
    monkeypatch.setenv("KNOWLEDGE_BASE_DIR", str(tmp_path))
    missing = tmp_path / "libraries" / LIB / "documents" / DOC / "source"

    assert resolve_source_file(LIB, DOC) is None
    assert not missing.exists()


def test_resolve_source_file_ordering_matches_ensure(tmp_path, monkeypatch) -> None:
    """字典序取第一，与 _ensure_source_file 同口径（两处漂移会让管线与预览各认一个文件）。"""
    source_dir = _make_doc_dir(tmp_path, monkeypatch, ["b.pdf", "a.pdf"])

    assert resolve_source_file(LIB, DOC) == str(source_dir / "a.pdf")


def test_prepare_source_falls_back_when_file_path_is_foreign(tmp_path, monkeypatch) -> None:
    """生产主路径：请求带的是开发机绝对路径，规范目录有原件 → 用规范目录的原件。"""
    source_dir = _make_doc_dir(tmp_path, monkeypatch, ["2404.14603v2.pdf"])

    resolved = prepare_source(LIB, DOC, FOREIGN_PATH)

    assert resolved == str(source_dir / "2404.14603v2.pdf")
    assert Path(resolved).parent == source_dir


def test_prepare_source_copies_local_path_when_dir_empty(tmp_path, monkeypatch) -> None:
    """上传通道行为不能退化：目录为空时把给定路径的原件复制进规范目录。"""
    monkeypatch.setenv("KNOWLEDGE_BASE_DIR", str(tmp_path))
    incoming = tmp_path / "incoming.pdf"
    incoming.write_bytes(b"%PDF-1.5\n")

    resolved = prepare_source(LIB, DOC, str(incoming))

    assert Path(resolved).read_bytes() == b"%PDF-1.5\n"
    assert Path(resolved).parent == tmp_path / "libraries" / LIB / "documents" / DOC / "source"


def test_prepare_source_raises_when_nothing_resolvable(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("KNOWLEDGE_BASE_DIR", str(tmp_path))

    import pytest

    with pytest.raises(RuntimeError, match="源文件不存在"):
        prepare_source(LIB, DOC, FOREIGN_PATH)
