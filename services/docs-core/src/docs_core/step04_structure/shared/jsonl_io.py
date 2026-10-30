"""jsonl IO ???doc_blocks_graph.jsonl + meta ????? build_id?step04/05/07/API ????"""
import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import docs_core.paths as paths

__all__ = [
    "atomic_write_text",
    "extract_build_id_from_markdown",
    "extract_build_id_from_meta",
    "get_doc_blocks_graph",
    "new_or_reuse_build_id",
]



# 孪生产物版本戳：md 头部注释与 meta.json 的 build_id 必须一致
def generate_build_id() -> str:
    from uuid import uuid4

    return uuid4().hex[:12]


def extract_build_id_from_markdown(markdown: str) -> Optional[str]:
    """从 content.md 头部读取 build_id 注释；无则返回 None。"""
    if not markdown:
        return None
    first_line = markdown.splitlines()[0].strip() if markdown.splitlines() else ""
    match = re.match(r"^<!--\s*build_id:\s*([0-9a-f]{12})\s*-->$", first_line)
    return match.group(1) if match else None


def extract_build_id_from_meta(meta: Optional[Dict[str, Any]]) -> Optional[str]:
    """从 graph meta.json 读取 build_id；无则返回 None。"""
    if not isinstance(meta, dict):
        return None
    value = meta.get("build_id")
    return str(value) if value else None


def _stamp_markdown_build_id(path: Path, build_id: str) -> None:
    """在 content.md 首行写入/替换 build_id 注释（无则前置）。"""
    if not build_id or not path.exists():
        return
    header = f"<!-- build_id: {build_id} -->"
    # 读写失败直接抛出：静默失败会让 meta.json 与 content.md 的 build_id 永久分叉，
    # 前端将一直显示“内容与图谱版本不一致”。由 _save_doc_blocks_graph 校验兜底。
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()
    if lines and re.match(r"^<!--\s*build_id:", lines[0].strip()):
        lines[0] = header
    else:
        lines.insert(0, header)
    # 临时文件 + 原子替换：避免写一半时被读取到残缺 md，也减少 Windows 下占用冲突。
    tmp_path = path.with_name(path.name + ".build_id.tmp")
    tmp_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(str(tmp_path), str(path))


def atomic_write_text(path: Path, text: str) -> None:
    """临时文件 + 原子替换写文本，避免写一半被读到。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(text, encoding="utf-8")
    os.replace(str(tmp_path), str(path))


def new_or_reuse_build_id(library_id: str, doc_id: str) -> str:
    """优先复用已有 build_id（用户编辑图谱不改配对），否则生成新戳并盖章 md。"""
    existing = None
    meta_path = paths.get_graph_meta_path(library_id, doc_id)
    if meta_path.exists():
        try:
            existing = extract_build_id_from_meta(json.loads(meta_path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            existing = None
    if existing:
        return existing
    md_path = paths.get_parsed_markdown_path(library_id, doc_id)
    if md_path.exists():
        try:
            existing = extract_build_id_from_markdown(md_path.read_text(encoding="utf-8"))
        except OSError:
            existing = None
    if existing:
        return existing
    return generate_build_id()


# 获取文档的块图谱
def get_doc_blocks_graph(library_id: str, doc_id: str) -> Optional[Dict[str, Any]]:
    jsonl_path = paths.get_graph_jsonl_path(library_id, doc_id)
    meta_path = paths.get_graph_meta_path(library_id, doc_id)
    if not jsonl_path.exists():
        return None
    return _read_doc_blocks_graph_split(jsonl_path, meta_path)


def get_doc_blocks_graph_pages(
    library_id: str, doc_id: str, page_from: int, page_to: int
) -> Optional[Dict[str, Any]]:
    """页级切片：只返回 [page_from, page_to]（0-based，含端点）内的块与块间边。

    动机（2026-10-30）：引用定位只需要目标页的 bbox 坐标（几 KB），旧链路却要整本
    doc_blocks_graph（单篇十几 MB），大书点引用要 3-5 秒。页签（树形/图谱）仍走整本。
    边只保留两端都在窗口内的（跨页父子关系属树形展示，定位不需要）。
    """
    if page_from > page_to:
        page_from, page_to = page_to, page_from
    jsonl_path = paths.get_graph_jsonl_path(library_id, doc_id)
    meta_path = paths.get_graph_meta_path(library_id, doc_id)
    if not jsonl_path.exists():
        return None
    nodes = []
    kept_ids = set()
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            node = json.loads(line)
            page_idx = node.get("page_idx")
            if not isinstance(page_idx, int) or not (page_from <= page_idx <= page_to):
                continue
            nodes.append(node)
            node_id = str(node.get("id") or "")
            if node_id:
                kept_ids.add(node_id)
    edges: list = []
    if meta_path.exists() and kept_ids:
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            edges = [
                edge
                for edge in meta.get("edges", [])
                if str(edge.get("from") or "") in kept_ids
                and str(edge.get("to") or "") in kept_ids
            ]
        except (OSError, json.JSONDecodeError):
            edges = []
    return {"nodes": nodes, "edges": edges}


def _read_doc_blocks_graph_split(jsonl_path: Path, meta_path: Path) -> Dict[str, Any]:
    nodes = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                nodes.append(json.loads(line))
    meta: Dict[str, Any] = {}
    if meta_path.exists():
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
    return {
        "nodes": nodes,
        "edges": meta.get("edges", []),
        "stats": meta.get("stats", {}),
        "generated_at": meta.get("generated_at", ""),
        "outlines": meta.get("outlines", []),
        "pages": meta.get("pages", []),
    }


# 写回 doc_blocks_graph (jsonl + meta.json)
def _write_doc_blocks_graph(library_id: str, doc_id: str, payload: Dict[str, Any]) -> str:
    nodes = payload.get("nodes")
    if isinstance(nodes, list) and nodes:
        jsonl_path = paths.get_graph_jsonl_path(library_id, doc_id)
        jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        with open(jsonl_path, "w", encoding="utf-8") as f:
            for node in nodes:
                f.write(json.dumps(node, ensure_ascii=False) + "\n")
    meta_path = paths.get_graph_meta_path(library_id, doc_id)
    meta = {
        "edges": payload.get("edges", []),
        "stats": payload.get("stats", {}),
        "generated_at": payload.get("generated_at", datetime.now().isoformat()),
        "build_id": new_or_reuse_build_id(library_id, doc_id),
        "outlines": payload.get("outlines", []),
        "pages": payload.get("pages", []),
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return str(meta_path)
