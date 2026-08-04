"""jsonl IO ???doc_blocks_graph.jsonl + meta ????? build_id?step04/05/07/API ????"""
import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import docs_core.paths as paths

__all__ = [
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
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return
    lines = content.splitlines()
    if lines and re.match(r"^<!--\s*build_id:", lines[0].strip()):
        lines[0] = header
    else:
        lines.insert(0, header)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return str(meta_path)
