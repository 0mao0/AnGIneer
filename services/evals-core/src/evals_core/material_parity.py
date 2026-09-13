"""B 层：素材传递性检查（jsonl → canonical/chunk → 向量）。

定位见 `docs/parse-struct-eval.md` 的 A/B/C 框架：**这不是评测分数，而是断言**——
"解析产出的内容有没有原样送到检索层"。产物是**缺失清单**，适合做 nightly 体检与 CI 断言。

检查项（逐文档）：
1. **内容落地**：`content_json` 里有文本、`plain_text` 却为空 → 内容被链路吃掉
   （2026-09-12 实踩过：chart/page_footnote/page_aside_text/code/algorithm 五类整类丢失）；
2. **块 → chunk**：有文本的块，其文本（空白无关、取前 24 字符）是否出现在该文档的 chunk 文本里
   → 检 canonical/chunk 构建环节有没有丢内容；
3. **chunk → 向量**：有 chunk 却没有向量点 → 向量化环节漏了（点数取自向量库按 doc_id 过滤计数）；
4. **索引存在性**：文档在 canonical 里有没有记录（fts/vectors 阶段跑没跑）。

设计约束：
- **不侵入解析链**：作为独立阅读器跑，失败只影响体检本身，不会让正常解析报错；
- 数据源可注入（`Sources`），单测不需要真实 DB/向量库；
- 库依赖：复用 `docs_core`（与 evals-core 同装在一个后端镜像里），不重复实现路径与存储逻辑。
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("evals_core.material_parity")

PROBE_CHARS = 24            # 块文本探针长度（空白无关比对）
DEFAULT_MIN_CHARS = 8       # 短于此长度的块不参与覆盖检查（页码、单字旁注等）
DEFAULT_TOLERANCE = 0.02    # 允许 2% 的覆盖缺口（归一化差异导致的对不上）
DEFAULT_MAX_DOCS = 200

_WS = re.compile(r"\s+")

# 以下块类型**按设计不进检索素材**（页眉/页脚/页码属版式附属信息，canonical 构建时会剔除），
# 不能算作"内容没送达"——否则体检每晚都会误报。
NOT_INDEXED_TYPES = {"page_header", "page_footer", "page_number"}
NOT_INDEXED_CATEGORIES = {"furniture"}


def norm(text: str | None) -> str:
    """空白无关归一：代码块换行、表格对齐空格都不该算差异。"""
    return _WS.sub("", text or "")


@dataclass
class DocReport:
    library_id: str
    doc_id: str
    blocks_total: int = 0
    blocks_with_text: int = 0
    blocks_uncovered: int = 0
    blocks_text_lost: int = 0
    chunks: int = 0
    vector_points: Optional[int] = None
    indexed: bool = False
    issues: list[str] = field(default_factory=list)
    samples: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    @property
    def coverage(self) -> Optional[float]:
        if not self.blocks_with_text:
            return None
        return 1.0 - self.blocks_uncovered / self.blocks_with_text

    def as_dict(self) -> dict:
        return {
            "library_id": self.library_id,
            "doc_id": self.doc_id,
            "indexed": self.indexed,
            "blocks_total": self.blocks_total,
            "blocks_with_text": self.blocks_with_text,
            "blocks_uncovered": self.blocks_uncovered,
            "blocks_text_lost": self.blocks_text_lost,
            "chunks": self.chunks,
            "vector_points": self.vector_points,
            "coverage": self.coverage,
            "issues": self.issues,
            "samples": self.samples,
        }


@dataclass
class Sources:
    """数据源注入点：默认实现读真实 docs_core 存储，单测可传假实现。"""
    list_docs: Callable[[], list[tuple[str, str]]]                  # [(library_id, doc_id)]
    load_nodes: Callable[[str, str], list[dict]]                    # 读 doc_blocks_graph.jsonl
    load_chunk_texts: Callable[[str, str], list[str]]               # 读 canonical chunk 文本
    has_canonical: Callable[[str, str], bool]
    count_vectors: Callable[[str, str], Optional[int]]              # 该文档的向量点数；None=不可用


def _expected_plain_text(node: dict) -> str:
    """该块"本应有"的文本——直接复用解析链自己的抽取函数，能覆盖未来新增的块类型。"""
    try:
        from docs_core.step04_structure.solo_engine import extract_plain_text

        content = node.get("content_json")
        if isinstance(content, dict) and content:
            return norm(extract_plain_text(str(node.get("block_type") or ""), content))
    except Exception:  # noqa: BLE001 docs_core 缺失或函数签名变化时退化为不检查该项
        return ""
    return ""


def _should_be_indexed(node: dict) -> bool:
    """该块按设计是否应该出现在检索素材里（页眉页脚页码等版式附属不算）。"""
    if str(node.get("block_type") or "") in NOT_INDEXED_TYPES:
        return False
    if str(node.get("layout_category") or "") in NOT_INDEXED_CATEGORIES:
        return False
    return int(node.get("is_active", 1) or 0) != 0


def check_document(library_id: str, doc_id: str, sources: Sources, *,
                   min_chars: int = DEFAULT_MIN_CHARS, tolerance: float = DEFAULT_TOLERANCE) -> DocReport:
    report = DocReport(library_id=library_id, doc_id=doc_id)
    nodes = sources.load_nodes(library_id, doc_id)
    report.blocks_total = len(nodes)
    if not nodes:
        report.issues.append("无解析产物（doc_blocks_graph.jsonl 为空）")
        return report

    texts: list[str] = []
    for node in nodes:
        plain = norm(node.get("plain_text"))
        expected = _expected_plain_text(node)
        if expected and not plain:
            report.blocks_text_lost += 1
            if len(report.samples) < 3:
                report.samples.append(f"[{node.get('block_type')}] 内容未落到 plain_text: {expected[:40]}")
        if len(plain) >= min_chars and _should_be_indexed(node):
            texts.append(plain)

    report.indexed = sources.has_canonical(library_id, doc_id)
    if not report.indexed:
        report.issues.append("未索引：canonical 无记录（fts/vectors 阶段未跑）")
    else:
        chunk_texts = sources.load_chunk_texts(library_id, doc_id)
        report.chunks = len(chunk_texts)
        chunk_blob = norm(" ".join(chunk_texts))
        report.blocks_with_text = len(texts)
        uncovered = [t for t in texts if t[:PROBE_CHARS] not in chunk_blob]
        report.blocks_uncovered = len(uncovered)
        if texts:
            coverage = 1.0 - len(uncovered) / len(texts)
            if coverage < 1.0 - tolerance:
                report.issues.append(
                    f"块→chunk 覆盖不足：{len(uncovered)}/{len(texts)} 个块文本未出现在 chunk 文本中"
                    f"（覆盖 {coverage:.3f}）")
                for text in uncovered[:3]:
                    report.samples.append(f"未覆盖块: {text[:44]}")

    points = sources.count_vectors(library_id, doc_id)
    report.vector_points = points
    if points is not None and report.chunks and points == 0:
        report.issues.append(f"chunk→向量缺失：{report.chunks} 个 chunk 但向量点为 0")

    if report.blocks_text_lost:
        report.issues.append(f"内容落地缺失：{report.blocks_text_lost} 个块 content_json 有文本但 plain_text 为空")
    return report


def _severity(reports: list[DocReport]) -> str:
    if not reports:
        return "ok"
    bad = 0
    for r in reports:
        if not r.ok:
            if r.blocks_uncovered and r.blocks_with_text and r.coverage is not None and r.coverage < 0.8:
                return "fail"
            if not r.indexed or (r.vector_points == 0) or r.blocks_text_lost:
                return "fail"
            bad += 1
    return "warn" if bad else "ok"


def run_check(*, libraries: Optional[list[str]] = None, max_docs: int = DEFAULT_MAX_DOCS,
              min_chars: int = DEFAULT_MIN_CHARS, tolerance: float = DEFAULT_TOLERANCE,
              sources: Optional[Sources] = None) -> dict:
    """跑一次素材检查：返回汇总（含缺失清单）。不抛异常——调用方按 severity 决定告警。"""
    sources = sources or default_sources()
    try:
        pairs = sources.list_docs()
    except Exception as exc:  # noqa: BLE001 体检自身失败不该拖垮调用方
        logger.exception("素材检查：列举文档失败")
        return {"severity": "error", "detail": f"{type(exc).__name__}: {str(exc)[:200]}",
                "docs_checked": 0, "docs_with_issues": 0, "issues": []}

    if libraries:
        wanted = set(libraries)
        pairs = [(lib, doc) for lib, doc in pairs if lib in wanted]
    pairs = pairs[:max_docs]

    reports: list[DocReport] = []
    for lib, doc in pairs:
        try:
            reports.append(check_document(lib, doc, sources, min_chars=min_chars, tolerance=tolerance))
        except Exception:  # noqa: BLE001 单篇失败不影响整批
            logger.exception("素材检查：单篇检查失败 lib=%s doc=%s", lib, doc)

    bad = [r for r in reports if not r.ok]
    totals = {
        "blocks": sum(r.blocks_total for r in reports),
        "blocks_with_text": sum(r.blocks_with_text for r in reports),
        "blocks_uncovered": sum(r.blocks_uncovered for r in reports),
        "blocks_text_lost": sum(r.blocks_text_lost for r in reports),
        "chunks": sum(r.chunks for r in reports),
        "vector_points": sum(r.vector_points or 0 for r in reports),
    }
    return {
        "severity": _severity(reports),
        "libraries": libraries or "all",
        "docs_checked": len(reports),
        "docs_with_issues": len(bad),
        "totals": totals,
        "issues": [r.as_dict() for r in bad],
    }


def render_summary(result: dict) -> str:
    """把体检结果渲染成一段人类可读的短报告（nightly 落盘/告警用）。"""
    if result.get("severity") == "error":
        return f"素材检查未完成：{result.get('detail')}"
    totals = result.get("totals") or {}
    lines = [
        f"素材检查（B 层）：severity={result.get('severity')}，"
        f"检查 {result.get('docs_checked')} 篇，其中 {result.get('docs_with_issues')} 篇有问题",
        f"块 {totals.get('blocks', 0)}，其中带文本 {totals.get('blocks_with_text', 0)}、"
        f"未被 chunk 覆盖 {totals.get('blocks_uncovered', 0)}、内容未落地 {totals.get('blocks_text_lost', 0)}；"
        f"chunk {totals.get('chunks', 0)}，向量点 {totals.get('vector_points', 0)}",
    ]
    if (totals.get("blocks_text_lost") or 0) > 0:
        lines.append("  提示：内容未落地多为「修复前解析」的存量产物（2026-09-12 修的那五类块），"
                     "重新解析后消失；若新解析文档仍有此告警，则是链路回归。")
    for issue in (result.get("issues") or [])[:5]:
        lines.append(f"  · {issue['library_id']}/{issue['doc_id']}: {'; '.join(issue['issues'])}")
        for sample in (issue.get("samples") or [])[:2]:
            lines.append(f"      - {sample}")
    return "\n".join(lines)


# ---- 默认数据源（真实 docs_core 存储） ----

_INDEX_DB = "knowledge_index.sqlite"


def default_sources() -> Sources:
    import docs_core.paths as paths
    from docs_core.step05_sqlite_fts.store.canonical_sql_store import CanonicalSQLiteStore

    store = CanonicalSQLiteStore()

    def list_docs() -> list[tuple[str, str]]:
        """按产物修改时间倒序列出所有已解析文档（体检优先看最近解析的）。"""
        base = paths.resolve_knowledge_base_dir() / "libraries"
        found: list[tuple[float, str, str]] = []
        if not base.is_dir():
            return []
        for lib_dir in sorted(p for p in base.iterdir() if p.is_dir()):
            docs_dir = lib_dir / "documents"
            if not docs_dir.is_dir():
                continue
            for doc_dir in docs_dir.iterdir():
                if not doc_dir.is_dir():
                    continue
                graph = doc_dir / "parsed" / "doc_blocks_graph.jsonl"
                if graph.is_file():
                    found.append((graph.stat().st_mtime, lib_dir.name, doc_dir.name))
        found.sort(reverse=True)
        return [(lib, doc) for _, lib, doc in found]

    def load_nodes(library_id: str, doc_id: str) -> list[dict]:
        graph = Path(paths.get_graph_jsonl_path(library_id, doc_id))
        if not graph.is_file():
            return []
        return [json.loads(line) for line in graph.read_text(encoding="utf-8").splitlines() if line.strip()]

    def has_canonical(library_id: str, doc_id: str) -> bool:
        with store.connect() as conn:
            row = conn.execute("SELECT 1 FROM canonical_documents WHERE doc_id = ? LIMIT 1", (doc_id,)).fetchone()
        return bool(row)

    def load_chunk_texts(library_id: str, doc_id: str) -> list[str]:
        with store.connect() as conn:
            rows = conn.execute("SELECT text_clean FROM canonical_chunks WHERE doc_id = ?", (doc_id,)).fetchall()
        return [str(r[0] or "") for r in rows]

    def count_vectors(library_id: str, doc_id: str) -> Optional[int]:
        """优先 Qdrant（生产 provider）；否则退到 sqlite canonical_vectors；都不可用返回 None。"""
        try:
            from docs_core.step06_vectors.qdrant_vector_store import QdrantVectorStore

            store_q = QdrantVectorStore()
            client = store_q._get_client()
            from qdrant_client import models

            res = client.count(
                collection_name=store_q._collection,
                count_filter=models.Filter(must=[models.FieldCondition(
                    key="doc_id", match=models.MatchValue(value=doc_id))]),
                exact=True,
            )
            return int(getattr(res, "count", 0))
        except Exception:  # noqa: BLE001 向量库不可用不该算作"缺失"
            pass
        try:
            with store.connect() as conn:
                row = conn.execute("SELECT COUNT(*) FROM canonical_vectors WHERE doc_id = ?", (doc_id,)).fetchone()
            return int(row[0]) if row else 0
        except Exception:  # noqa: BLE001 表不存在（provider=qdrant 时 canonical_vectors 为空表）
            return None

    return Sources(list_docs=list_docs, load_nodes=load_nodes, load_chunk_texts=load_chunk_texts,
                   has_canonical=has_canonical, count_vectors=count_vectors)
