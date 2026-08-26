"""为 OpenRAGBenchmark 文档的图表生成 VLM 文字描述。

读取每个文档的 doc_blocks_graph.jsonl，找出 chart/image 块（带 image_path），
调用远程 Qwen3.6-35B-A3B-FP8（多模态）生成英文描述，写入节点
``figure_description`` 字段（不动原始 plain_text）。支持断点续跑与并发。

用法：
    python scripts/open_ragbench/generate_figure_descriptions.py [--limit N] [--workers 4]
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import requests


REPO_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_INDEX = REPO_ROOT / "data" / "knowledge_base" / "knowledge_index.sqlite"
DOCS_ROOT = (
    REPO_ROOT
    / "data"
    / "knowledge_base"
    / "libraries"
    / "lib-b07ed174"
    / "documents"
)

CHAT_URL = "https://ai.bim-ace.com/chat/v1/chat/completions"
CHAT_KEY = os.getenv("ANGINEER_CHAT_API_KEY", "shiw-0968e8bb57a44abe888f9f7f9d5bfc85")
MODEL = "Qwen3.6-35B-A3B-FP8"

PROMPT = (
    "You are analyzing a figure extracted from an academic paper. "
    "Describe what this figure shows in 2-4 concise English sentences. "
    "Include: the type of figure (chart/table/illustration), the main content or trend, "
    "any notable data points or values, and the key takeaway. "
    "Be specific and factual based only on the image."
)

FIGURE_TYPES = {"chart", "image", "figure", "image_block"}


def _mime_for(path: Path) -> str:
    suffix = path.suffix.lower()
    return "image/png" if suffix == ".png" else "image/jpeg"


def describe_image(img_path: Path, timeout: int = 120) -> str:
    b64 = base64.b64encode(img_path.read_bytes()).decode("ascii")
    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:{_mime_for(img_path)};base64,{b64}"}},
                    {"type": "text", "text": PROMPT},
                ],
            }
        ],
        "max_tokens": 400,
        "temperature": 0.2,
    }
    resp = requests.post(
        CHAT_URL,
        headers={"Authorization": f"Bearer {CHAT_KEY}", "Content-Type": "application/json"},
        json=payload,
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unexpected chat response: {data}") from exc
    return str(content or "").strip()


def list_doc_ids() -> list[str]:
    import sqlite3

    conn = sqlite3.connect(KNOWLEDGE_INDEX)
    try:
        rows = conn.execute(
            "SELECT doc_id FROM canonical_documents WHERE library_id='lib-b07ed174' ORDER BY doc_id"
        ).fetchall()
        return [row[0] for row in rows]
    finally:
        conn.close()


def figure_nodes(doc_id: str) -> list[dict[str, Any]]:
    graph_path = DOCS_ROOT / doc_id / "parsed" / "doc_blocks_graph.jsonl"
    if not graph_path.exists():
        return []
    nodes: list[dict[str, Any]] = []
    for line in graph_path.read_text(encoding="utf-8").splitlines():
        node = json.loads(line)
        if str(node.get("block_type") or "").strip() in FIGURE_TYPES:
            nodes.append(node)
    return nodes


def resolve_image_path(doc_id: str, image_path: str) -> Path:
    p = Path(str(image_path or ""))
    if not p.is_absolute():
        p = DOCS_ROOT / doc_id / "parsed" / p
    return p


def main() -> int:
    parser = argparse.ArgumentParser(description="为 OpenRAGBenchmark 图表生成 VLM 描述")
    parser.add_argument("--limit", type=int, default=0, help="每个文档最多处理的图数量（0=不限）")
    parser.add_argument("--workers", type=int, default=4, help="并发请求数")
    args = parser.parse_args()

    doc_ids = list_doc_ids()
    lock = threading.Lock()
    total_done = 0
    total_skipped = 0
    total_errors = 0

    def process_node(doc_id: str, node: dict[str, Any]) -> tuple[str, str | None]:
        nonlocal total_done, total_skipped, total_errors
        block_uid = str(node.get("block_uid") or node.get("id") or "")
        if str(node.get("figure_description") or "").strip():
            with lock:
                total_skipped += 1
            return block_uid, None
        image_path = str(node.get("image_path") or "").strip()
        if not image_path:
            return block_uid, None
        resolved = resolve_image_path(doc_id, image_path)
        if not resolved.exists():
            with lock:
                total_errors += 1
            return block_uid, f"MISSING_IMAGE {resolved}"
        try:
            description = describe_image(resolved)
        except Exception as exc:  # noqa: BLE001
            with lock:
                total_errors += 1
            return block_uid, f"ERROR {type(exc).__name__}: {exc}"
        with lock:
            total_done += 1
            if total_done % 20 == 0:
                print(f"  ... done {total_done}, skipped {total_skipped}, errors {total_errors}", flush=True)
        return block_uid, description

    for doc_id in doc_ids:
        nodes = figure_nodes(doc_id)
        if not nodes:
            continue
        print(f"[{doc_id}] {len(nodes)} figure nodes", flush=True)
        selected = nodes[: args.limit] if args.limit > 0 else nodes
        graph_path = DOCS_ROOT / doc_id / "parsed" / "doc_blocks_graph.jsonl"
        lines = graph_path.read_text(encoding="utf-8").splitlines()
        index_by_uid = {}
        for line_no, line in enumerate(lines):
            node = json.loads(line)
            uid = str(node.get("block_uid") or node.get("id") or "")
            if uid:
                index_by_uid[uid] = line_no

        updated = {}
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {
                pool.submit(process_node, doc_id, node): str(node.get("block_uid") or node.get("id") or "")
                for node in selected
            }
            for future in as_completed(futures):
                uid, description = future.result()
                if description is not None:
                    updated[uid] = description

        if updated:
            changed = 0
            for line_no, line in enumerate(lines):
                node = json.loads(line)
                uid = str(node.get("block_uid") or node.get("id") or "")
                if uid in updated:
                    node["figure_description"] = updated[uid]
                    lines[line_no] = json.dumps(node, ensure_ascii=False)
                    changed += 1
            if changed:
                graph_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            print(f"  wrote {changed} descriptions", flush=True)

    print(f"TOTAL done={total_done} skipped={total_skipped} errors={total_errors}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
