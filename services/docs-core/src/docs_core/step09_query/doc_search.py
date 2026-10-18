"""文档级检索 + 批量读页（枚举型任务的检索底座）。

背景（2026-10-18 Harvey LAB 实踩）：段落级 top-20 检索在「列举全部/每一个」类问题上
结构性失败——266 个 matter / 9000 篇文档里，命中段落只覆盖十余篇文档，枚举必然漏项；
而精确名查询 9/9 命中、主题查询 0/9，说明缺的是「文档级候选清单」而不是相似度。

本模块提供两件事（都不重跑解析，只读既有 canonical 索引）：
1. ``search_documents``：FTS 命中按文档聚合（含文件名/路径命中），按 matter 分组，
   返回紧凑的 matter 卡片（最佳证据片段 + 命中文档标题）。默认 40 篇、上限 120 篇。
2. ``read_documents``：按 doc_id 批量读页（head=从头读，match=读命中段落），
   每篇截断到 max_chars_per_doc，单次最多 8 篇，供模型逐篇确认。

``doc_catalog``（可选表）：把导入时的 DMS 路径元数据（matter_id/folder/filename）
落到组的 index 库里。没有该表时退化为「按文档分组」，功能不受影响；有该表时
枚举结果按 matter 归并——与官方 harness 直接看到 DMS 目录树的信息面对齐。
"""
from __future__ import annotations

import logging
import re
import sqlite3
from typing import Any, Dict, List, Optional

from docs_core.library_registry import resolve_index_db_path

logger = logging.getLogger(__name__)

MAX_DOCS = 120
MAX_READ_DOCS = 8
_SNIPPET_CHARS = 200
_MATTER_CARDS = 40

_CATALOG_DDL = """
CREATE TABLE IF NOT EXISTS doc_catalog (
    doc_id      TEXT PRIMARY KEY,
    library_id  TEXT NOT NULL,
    matter_id   TEXT NOT NULL DEFAULT '',
    folder      TEXT NOT NULL DEFAULT '',
    rel_path    TEXT NOT NULL DEFAULT '',
    filename    TEXT NOT NULL DEFAULT '',
    doc_type    TEXT NOT NULL DEFAULT '',
    source      TEXT NOT NULL DEFAULT '',
    updated_at  TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_doc_catalog_library ON doc_catalog(library_id);
CREATE INDEX IF NOT EXISTS idx_doc_catalog_matter ON doc_catalog(library_id, matter_id);
CREATE INDEX IF NOT EXISTS idx_doc_catalog_filename ON doc_catalog(library_id, filename);
"""

_WORD_RE = re.compile(r"[0-9A-Za-z_\u4e00-\u9fff]+")


def _connect(library_id: str) -> sqlite3.Connection:
    path = resolve_index_db_path(library_id)
    conn = sqlite3.connect(str(path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_catalog(conn: sqlite3.Connection) -> None:
    """幂等建表：只在回填脚本需要时执行（不迁移、不改既有表）。"""
    conn.executescript(_CATALOG_DDL)
    conn.commit()


def has_catalog(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "select 1 from sqlite_master where type='table' and name='doc_catalog'"
    ).fetchone()
    return row is not None


def _tokens(query: str) -> List[str]:
    return [w for w in _WORD_RE.findall(query or "") if len(w) >= 2][:12]


def _fts_match(tokens: List[str], *, phrase: bool) -> Optional[str]:
    if not tokens:
        return None
    if phrase and len(tokens) > 1:
        return '"' + " ".join(tokens) + '"'
    return " ".join(tokens)


def _catalog_map(conn: sqlite3.Connection, library_id: str, doc_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    if not doc_ids or not has_catalog(conn):
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for start in range(0, len(doc_ids), 400):
        chunk = doc_ids[start : start + 400]
        marks = ",".join("?" * len(chunk))
        rows = conn.execute(
            f"select doc_id, matter_id, folder, rel_path, filename from doc_catalog "
            f"where library_id=? and doc_id in ({marks})",
            [library_id, *chunk],
        )
        for row in rows:
            out[row["doc_id"]] = dict(row)
    return out


def _title_hits(
    conn: sqlite3.Connection, library_id: str, tokens: List[str], limit: int
) -> Dict[str, Any]:
    """文件名/路径命中（枚举题常以文档类型命名，如 second-request-*.docx）。

    任一 token 命中即入选（OR），按命中 token 数计分；若文件名/路径含连续短语
    （如 "second request"，连字符/下划线归一成空格）额外加权——这是枚举题最强的
    「文档类型」信号，不能被泛词（hsr）淹没。多词 query 只命中一个泛词的文件名不算
    信号（hsr-filing-* 不是二次问询），要求至少命中两个 token 或整串短语。
    """
    if not tokens or not has_catalog(conn):
        return {}
    like = " or ".join("(filename like ? or rel_path like ?)" for _ in tokens)
    params: List[Any] = [library_id]
    for token in tokens:
        params += [f"%{token}%", f"%{token}%"]
    rows = conn.execute(
        f"select doc_id, filename, rel_path from doc_catalog where library_id=? and ({like}) limit ?",
        [*params, max(limit * 8, 400)],
    )
    phrase = " ".join(tokens).lower()
    min_tokens = 2 if len(tokens) >= 2 else 1
    out: Dict[str, Any] = {}
    for row in rows:
        hay = f"{row['filename']} {row['rel_path']}".lower()
        flat = hay.replace("-", " ").replace("_", " ")
        matched = sum(1 for token in tokens if token.lower() in hay)
        phrase_hit = phrase in flat
        if matched < min_tokens and not phrase_hit:
            continue
        out[row["doc_id"]] = (matched, phrase_hit)
    return out


def _norm_name(text: str) -> str:
    """文件名归一：小写 + 连字符/下划线/多空格压成单空格（second-request → second request）。"""
    return re.sub(r"[\s\-_]+", " ", str(text or "").lower()).strip()


def _catalog_filter_hits(
    conn: sqlite3.Connection,
    library_id: str,
    phrases: List[str],
    doc_type: Optional[str],
    limit: int = 400,
) -> Dict[str, str]:
    """目录谓词：按文件名/路径短语（AND）筛选，返回 doc_id → 文件名。

    这是枚举题最确定的通道：文档类型写在文件名里（second-request-*、hsr-withdrawal-*），
    直接按路径过滤比 FTS 排序精确得多（题 001 实测：17 个候选命中真值 5/6）。
    每个短语归一后要求逐词出现；多短语之间是 AND（调用方可用多次调用表达 OR）。
    """
    if not phrases or not has_catalog(conn):
        return {}
    clauses: List[str] = []
    params: List[Any] = [library_id]
    normalized = [_norm_name(p) for p in phrases if _norm_name(p)]
    for phrase in normalized:
        for token in phrase.split():
            clauses.append("(filename like ? or rel_path like ?)")
            params += [f"%{token}%", f"%{token}%"]
    if not clauses:
        return {}
    where = " and ".join(clauses)
    if doc_type:
        where += " and doc_type=?"
        params.append(str(doc_type).lower().lstrip("."))
    try:
        rows = conn.execute(
            f"select doc_id, filename, rel_path from doc_catalog where library_id=? and ({where}) limit ?",
            [*params, limit],
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    out: Dict[str, str] = {}
    for row in rows:
        flat = _norm_name(f"{row['filename']} {row['rel_path']}")
        if all(phrase in flat for phrase in normalized):
            out[row["doc_id"]] = row["filename"]
    return out


def list_matters(library_id: str, limit: int = 300) -> Dict[str, Any]:
    """matter 清单（等价于对 DMS 做一次 ls）：matter_id + 文档数 + 代表文件名。"""
    conn = _connect(library_id)
    try:
        if not has_catalog(conn):
            return {"catalog": False, "total": 0, "matters": []}
        rows = conn.execute(
            "select matter_id, count(*) as n, min(filename) as sample, max(folder) as folder "
            "from doc_catalog where library_id=? group by matter_id order by matter_id limit ?",
            (library_id, max(1, min(int(limit or 300), 500))),
        ).fetchall()
        total = conn.execute(
            "select count(distinct matter_id) from doc_catalog where library_id=?", (library_id,)
        ).fetchone()[0]
    finally:
        conn.close()
    return {
        "catalog": True,
        "total": int(total),
        "matters": [
            {"matter_id": r["matter_id"], "docs": int(r["n"]), "sample": r["sample"], "folder": r["folder"]}
            for r in rows
        ],
    }


def _match_plans(tokens: List[str], *, include_loose: bool = True) -> List[Any]:
    """FTS 查询计划：整串短语（最高权重）→ 相邻二元短语 → 全词 AND。

    枚举题的 query 常是「主题词 + 限定词」（HSR second request），整串短语过严会漏掉
    只写 "second request" 的文档；二元短语补上这层，且权重高于松散 AND。
    include_loose=False 时不给 AND 计划：候选集会被宽到几百个 matter（实测 241 个），
    枚举视图失去意义；只有短语通道命中过少时才放开。
    """
    if not tokens:
        return []
    if len(tokens) == 1:
        return [(_fts_match(tokens, phrase=False), 2.0)]
    plans: List[Any] = [(_fts_match(tokens, phrase=True), 3.0)]
    for left, right in zip(tokens, tokens[1:]):
        plans.append((f'"{left} {right}"', 2.0))
    if include_loose:
        plans.append((_fts_match(tokens, phrase=False), 1.0))
    deduped: List[Any] = []
    seen = set()
    for match, weight in plans:
        if match and match not in seen:
            seen.add(match)
            deduped.append((match, weight))
    return deduped[:5]


def _text_hits(
    conn: sqlite3.Connection,
    library_id: str,
    tokens: List[str],
    limit: int,
    *,
    include_loose: bool = True,
) -> List[Dict[str, Any]]:
    """FTS 命中按文档聚合（多查询计划加权）。

    FTS5 的 bm25() 不能在 GROUP BY 聚合上下文用（2026-10-18 实踩），所以先取命中段落
    明细、在 Python 侧按 doc 聚合；单次取 limit*20 条段落足够覆盖 limit 篇文档。
    """
    merged: Dict[str, Dict[str, Any]] = {}
    for match, weight in _match_plans(tokens, include_loose=include_loose):
        try:
            rows = conn.execute(
                "select doc_id, chunk_id, text_clean, bm25(canonical_chunk_fts) as score "
                "from canonical_chunk_fts where canonical_chunk_fts match ? "
                "and doc_id in (select doc_id from canonical_documents where library_id=?) "
                "order by score limit ?",
                (match, library_id, max(limit * 20, 200)),
            ).fetchall()
        except sqlite3.OperationalError as exc:  # 非法 FTS 语法一律退化为无命中
            logger.warning("doc_search FTS 语法失败(%r): %s", match, exc)
            continue
        for row in rows:
            doc_id = row["doc_id"]
            entry = merged.setdefault(
                doc_id, {"doc_id": doc_id, "hits": 0, "score": 0.0, "best_text": "", "best_chunk": ""}
            )
            entry["hits"] += 1
            entry["score"] += weight
            if not entry["best_text"]:
                entry["best_text"] = row["text_clean"] or ""
                entry["best_chunk"] = row["chunk_id"] or ""
    return sorted(merged.values(), key=lambda x: (-x["score"], -x["hits"]))


def _page_of_chunk(conn: sqlite3.Connection, chunk_id: str) -> int:
    if not chunk_id:
        return 0
    row = conn.execute("select page_start from canonical_chunks where chunk_id=?", (chunk_id,)).fetchone()
    return int(row["page_start"] or 0) if row else 0


def _snippet(text: str, limit: int = _SNIPPET_CHARS) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def _title_map(conn: sqlite3.Connection, doc_ids: List[str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for start in range(0, len(doc_ids), 400):
        chunk = doc_ids[start : start + 400]
        marks = ",".join("?" * len(chunk))
        for row in conn.execute(
            f"select doc_id, title from canonical_documents where doc_id in ({marks})", chunk
        ):
            out[row["doc_id"]] = row["title"]
    return out


def search_documents(
    *,
    library_id: str = "default",
    query: str,
    limit: int = 40,
    per_matter: int = 2,
    filename_contains: Optional[List[str]] = None,
    doc_type: Optional[str] = None,
) -> Dict[str, Any]:
    """文档级检索：返回按 matter 归并的候选清单（枚举视图）。

    filename_contains：目录谓词（短语列表，AND）——按文件名/路径过滤，高于 FTS 的确定性信号；
    doc_type：限定扩展名（xlsx/docx/pdf…）。两者只在有 doc_catalog 的库生效。
    """
    limit = max(1, min(int(limit or 40), MAX_DOCS))
    per_matter = max(1, min(int(per_matter or 2), 10))
    tokens = _tokens(query)
    if not tokens and not filename_contains:
        return {"error": "缺少有效检索词", "query": query}

    conn = _connect(library_id)
    catalog: Dict[str, Dict[str, Any]] = {}
    docs: List[Dict[str, Any]] = []
    matter_list: List[Dict[str, Any]] = []
    groups: Dict[str, Dict[str, Any]] = {}
    candidates: Dict[str, Dict[str, Any]] = {}
    catalog_docs: Dict[str, str] = {}
    try:
        text_rows = _text_hits(conn, library_id, tokens, limit, include_loose=False) if tokens else []
        if tokens and len(text_rows) < 5:
            # 短语通道过窄（术语写法不一/复数/换行断裂）时才放开松散 AND，避免漏召回
            text_rows = _text_hits(conn, library_id, tokens, limit, include_loose=True)
        title_scores = _title_hits(conn, library_id, tokens, limit) if tokens else {}
        candidates = {r["doc_id"]: r for r in text_rows}
        for doc_id, (matched_tokens, phrase_hit) in title_scores.items():
            entry = candidates.setdefault(
                doc_id, {"doc_id": doc_id, "hits": 0, "score": 0.0, "best_text": "", "best_chunk": ""}
            )
            entry["hits"] = max(1, entry["hits"])
            entry["score"] += 4.0 * matched_tokens + (12.0 if phrase_hit else 0.0)
            entry["title_hit"] = True
        if filename_contains:
            catalog_docs = _catalog_filter_hits(conn, library_id, filename_contains, doc_type)
            for doc_id, filename in catalog_docs.items():
                entry = candidates.setdefault(
                    doc_id, {"doc_id": doc_id, "hits": 0, "score": 0.0, "best_text": "", "best_chunk": ""}
                )
                entry["hits"] = max(1, entry["hits"])
                entry["score"] += 30.0  # 目录谓词命中：确定性最高，排在最前
                entry["catalog_hit"] = True
                entry["catalog_title"] = filename

        catalog = _catalog_map(conn, library_id, list(candidates)[: max(limit * 8, 400)])
        # matter 优先分配：同一 matter 最多 per_matter 篇进 docs，避免大 matter 挤掉其它候选。
        # 先按分数取前 400 个候选再分组——候选可能上千（泛词命中），全量分组会让 matter 数失真。
        ranked = sorted(candidates.values(), key=lambda x: (-x["score"], -x["hits"]))[:400]
        for entry in ranked:
            cat = catalog.get(entry["doc_id"]) or {}
            key = cat.get("matter_id") or f"doc:{entry['doc_id']}"
            group = groups.setdefault(key, {"matter_id": key, "score": 0.0, "entries": []})
            group["entries"].append(entry)
            group["score"] = max(group["score"], entry["score"])
        ordered_groups = sorted(groups, key=lambda k: (-groups[k]["score"], k))

        chosen: List[Dict[str, Any]] = []
        for key in ordered_groups:
            entries = sorted(groups[key]["entries"], key=lambda x: (-x["score"], -x["hits"]))
            for entry in entries[:per_matter]:
                if len(chosen) >= limit:
                    break
                chosen.append(entry)
            if len(chosen) >= limit:
                break

        card_ids: List[str] = []
        for key in ordered_groups[:_MATTER_CARDS]:
            for entry in groups[key]["entries"][:per_matter]:
                card_ids.append(entry["doc_id"])
        title_map = _title_map(conn, card_ids) if card_ids else {}

        for entry in chosen:
            cat = catalog.get(entry["doc_id"]) or {}
            docs.append({
                "doc_id": entry["doc_id"],
                "title": cat.get("filename") or title_map.get(entry["doc_id"]) or entry["doc_id"],
                "matter_id": cat.get("matter_id") or "",
                "folder": cat.get("folder") or "",
                "hits": entry["hits"],
                "title_hit": bool(entry.get("title_hit")),
                "snippet": _snippet(entry.get("best_text") or ""),
                "page": _page_of_chunk(conn, entry.get("best_chunk") or "") + 1,
            })

        for key in ordered_groups[:_MATTER_CARDS]:
            entries = sorted(groups[key]["entries"], key=lambda x: (-x["score"], -x["hits"]))
            best = entries[0]
            best_cat = catalog.get(best["doc_id"]) or {}
            matched_docs = [
                catalog_docs[e["doc_id"]] for e in entries if e["doc_id"] in catalog_docs
            ]
            card = {
                "matter_id": key,
                "n_docs": len(entries),
                "folder": best_cat.get("folder") or "",
                "best": {
                    "doc_id": best["doc_id"],
                    "title": best_cat.get("filename") or title_map.get(best["doc_id"]) or best["doc_id"],
                    "snippet": _snippet(best.get("best_text") or "", 160),
                },
                "docs": [
                    {
                        "doc_id": entry["doc_id"],
                        "title": (catalog.get(entry["doc_id"]) or {}).get("filename")
                        or title_map.get(entry["doc_id"])
                        or entry["doc_id"],
                    }
                    for entry in entries[:per_matter]
                ],
            }
            if matched_docs:
                card["catalog_hit"] = True
                card["matched_docs"] = matched_docs[:5]
            matter_list.append(card)
    finally:
        conn.close()

    # 有 catalog 时 docs 与 matters 内容重复（都带 doc_id/title），只保留紧凑的 matters 视图，
    # 避免单次工具结果膨胀（2026-10-18 实踩：双份清单把上下文顶到 155k tokens 触发 400）。
    # 注意：不要留空 docs 数组——模型会把 "docs": [] 读成「没找到」，随后退化成回显题面。
    result: Dict[str, Any] = {
        "query": query,
        "library_id": library_id,
        "total_docs": len(candidates),
        "total_matters": len(groups),
        "returned_matters": len(matter_list),
        "returned_docs": len(docs),
        "matters": matter_list,
        "catalog": bool(catalog),
        "note": (
            "matters 为按 matter 归并的枚举视图（best.snippet 是最佳证据片段，docs 列出该 matter 的命中文档）。"
            "catalog_hit=true 的卡片是文件名/路径谓词命中（确定性信号，优先核对）；"
            "片段只是线索：确认资格必须用 doc_read 读正文，不要只凭片段下结论。"
        ),
    }
    if filename_contains:
        result["filter"] = {
            "filename_contains": list(filename_contains),
            "doc_type": doc_type or "",
            "catalog_docs": len(catalog_docs),
        }
    if not catalog:
        result["docs"] = docs
    return result


def _query_terms(query: str) -> List[str]:
    return _tokens(query)[:6]


def read_documents(
    *,
    library_id: str = "default",
    doc_ids: List[str],
    query: str = "",
    max_chars_per_doc: int = 1200,
    mode: str = "head",
) -> Dict[str, Any]:
    """批量读页：head=从头按页读；match=读与 query 相关的段落（无命中回落 head）。"""
    ids = [str(d).strip() for d in (doc_ids or []) if str(d).strip()][:MAX_READ_DOCS]
    if not ids:
        return {"error": "缺少 doc_ids"}
    max_chars = max(200, min(int(max_chars_per_doc or 1200), 4000))
    conn = _connect(library_id)
    try:
        catalog = _catalog_map(conn, library_id, ids)
        out: List[Dict[str, Any]] = []
        for doc_id in ids:
            doc_meta = conn.execute(
                "select title, page_count from canonical_documents where doc_id=?", (doc_id,)
            ).fetchone()
            if doc_meta is None:
                out.append({"doc_id": doc_id, "error": "文档不存在或不属于本库"})
                continue
            rows: List[sqlite3.Row] = []
            if mode == "match" and query:
                terms = _query_terms(query)
                if terms:
                    like = " and ".join("text_clean like ?" for _ in terms)
                    rows = conn.execute(
                        f"select text_clean, page_start, chunk_id from canonical_chunks "
                        f"where doc_id=? and {like} order by page_start, chunk_id limit 6",
                        (doc_id, *[f"%{t}%" for t in terms]),
                    ).fetchall()
            if not rows:
                rows = conn.execute(
                    "select text_clean, page_start, chunk_id from canonical_chunks "
                    "where doc_id=? order by page_start, chunk_id limit 12",
                    (doc_id,),
                ).fetchall()

            parts: List[str] = []
            total = 0
            used = 0
            for row in rows:
                text = (row["text_clean"] or "").strip()
                if not text:
                    continue
                total += len(text)
                if used >= max_chars:
                    continue
                budget = max_chars - used
                piece = text[:budget]
                parts.append(f"[p{int(row['page_start']) + 1}] {piece}")
                used += len(piece)
            cat = catalog.get(doc_id) or {}
            out.append({
                "doc_id": doc_id,
                "title": cat.get("filename") or doc_meta["title"],
                "matter_id": cat.get("matter_id") or "",
                "page_count": int(doc_meta["page_count"] or 0),
                "chars": used,
                "total_chars": total,
                "truncated": total > used,
                "text": "\n".join(parts),
            })
    finally:
        conn.close()
    return {"docs": out, "mode": mode, "note": "text 中 [pN] 为页码；truncated=true 表示只读了开头部分。"}
