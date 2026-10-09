"""拒答前提对账（nightly 断言）：拒答标注的前提会随语料变动失效，只告警不阻断。

背景（2026-10-09 实踩，见 docs/report-refusal-premise-drift-20261009.md）：
open-ragbench 拒答集 39 题的前提是「源论文不在库」；2026-09-21/09-23 两次语料扩充
把其中 6 篇补进库后，标注静默过期 18 天——这 6 题同时在拒答集与主集被判「该拒没拒」。
本模块把「前提仍成立」做成每晚断言（与素材检查并列），供 nightly 与 import_kb 自检复用。

支持的前提种类（写在题面元数据里）：
- ``doc_absent``：前提=某源文档缺席。open-ragbench 拒答题从 tags 里的 arXiv 号自动派生；
  **匹配忽略版本号**——标注写 v3、入库的是 v4 同样是前提失效（2026-10-09 实踩）。
- ``keyword_zero_hit``：前提=关键词在库内 0 命中（eval_1 三题在 answer_gold.premise 显式声明）。
- 解析不出前提的题计入 ``unknown``，只报告、不判违规。

定性：这是**标注与语料的一致性断言**，不是评测分数。语料扩充是合法操作，
因此永远只告警（warn）不阻断；存储不可访问时记 error 并跳过（环境问题≠前提失效）。
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger("evals_core.refusal_premise")

_SEVERITY_OK = "ok"
_SEVERITY_WARN = "warn"
_SEVERITY_ERROR = "error"
_ARXIV_RE = re.compile(r"^(\d{4}\.\d{4,5})(v\d+)?$")


# ---------- 前提解析 ----------

def _parse_json(raw: Any, default):
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw) if raw else default
    except (TypeError, ValueError):
        return default


def _paper_id(name: str) -> str:
    """arXiv 名 → 论文号（去版本）：2412.18501v3.pdf → 2412.18501；非 arXiv 名返回空串。"""
    m = re.match(r"\s*(\d{4}\.\d{4,5})", str(name or ""))
    return m.group(1) if m else ""


def resolve_premises(gold: dict, tags: Any) -> List[dict]:
    """解析一道拒答题的前提声明；返回列表（可为空=unknown）。

    优先级：answer_gold.premise 显式声明 > tags 里的 arXiv 号派生。
    """
    out: List[dict] = []
    declared = (gold or {}).get("premise")
    items = declared if isinstance(declared, list) else ([declared] if isinstance(declared, dict) else [])
    for it in items:
        if isinstance(it, dict) and it.get("kind"):
            out.append(dict(it))
    if out:
        return out
    for t in (tags or []):
        m = _ARXIV_RE.match(str(t).strip())
        if m:
            out.append({"kind": "doc_absent", "doc": m.group(1)})
            break
    return out


# ---------- 数据源（可注入） ----------

class Sources:
    """默认实现读真实 evals DB 与 docs_core 存储；单测传假实现。"""

    def evals_db_path(self) -> str:
        from evals_core.storage import result_store
        return str(result_store._DB_PATH)

    def list_refusal_items(self) -> List[dict]:
        """全库拒答标注题（refusal_expected=true）：dataset/question/library/tags/gold。"""
        db = self.evals_db_path()
        out: List[dict] = []
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            rows = conn.execute(
                "SELECT dataset_id, question_id, tags, library_id, answer_gold "
                "FROM eval_question "
                "WHERE answer_gold LIKE '%refusal_expected%' OR answer_gold LIKE '%正确行为是拒答%'"
            ).fetchall()
        finally:
            conn.close()
        for dataset_id, question_id, tags, library_id, gold_raw in rows:
            gold = _parse_json(gold_raw, {})
            if not gold.get("refusal_expected"):
                continue
            out.append({
                "dataset_id": dataset_id, "question_id": question_id,
                "library_id": library_id or "",
                "tags": _parse_json(tags, []), "gold": gold,
            })
        return out

    def doc_present(self, library_id: str, doc: str) -> Optional[str]:
        """该文档是否在库；返回查到的文件名（命中）或 None（缺席）。存储不可用抛异常。"""
        import docs_core.paths as paths
        from docs_core import library_registry

        paper = _paper_id(doc)
        needle = paper or str(doc)
        like = f"%{needle}%"

        # 1) meta 库 nodes（上传登记，UI/所有入库途径都会落这里）
        meta_db = str(paths.resolve_knowledge_meta_db_path())
        conn = sqlite3.connect(f"file:{meta_db}?mode=ro", uri=True)
        try:
            rows = conn.execute(
                "SELECT title, file_path FROM nodes WHERE library_id=? "
                "AND (deleted IS NULL OR deleted=0) AND (title LIKE ? OR file_path LIKE ?)",
                (library_id, like, like)).fetchall()
        finally:
            conn.close()
        for title, file_path in rows:
            name = str(title or "") or str(file_path or "")
            if paper:
                if _paper_id(name) == paper:
                    return name
            elif needle in name:
                return name

        # 2) canonical 索引（title 列可能只是 doc_id，故两个字段都查；分库单文件布局无 library_id 列）
        index_db = str(library_registry.resolve_index_db_path(library_id))
        if os.path.exists(index_db):
            conn = sqlite3.connect(f"file:{index_db}?mode=ro", uri=True)
            try:
                cols = [r[1] for r in conn.execute("PRAGMA table_info(canonical_documents)")]
                if "library_id" in cols:
                    rows = conn.execute(
                        "SELECT title, source_file_name FROM canonical_documents WHERE library_id=? "
                        "AND (title LIKE ? OR source_file_name LIKE ?)",
                        (library_id, like, like)).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT title, source_file_name FROM canonical_documents "
                        "WHERE title LIKE ? OR source_file_name LIKE ?",
                        (like, like)).fetchall()
            finally:
                conn.close()
            for title, source_name in rows:
                for name in (str(title or ""), str(source_name or "")):
                    if paper and _paper_id(name) == paper:
                        return name or needle
                    if not paper and needle in name:
                        return name
        return None

    def keyword_present(self, library_id: str, term: str) -> bool:
        """关键词在库内是否有命中（存在即真）。存储不可用抛异常。"""
        from docs_core import library_registry

        index_db = str(library_registry.resolve_index_db_path(library_id))
        if not os.path.exists(index_db):
            return False
        like = f"%{term}%"
        conn = sqlite3.connect(f"file:{index_db}?mode=ro", uri=True)
        try:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(canonical_documents)")]
            if "library_id" in cols:
                hit = conn.execute(
                    "SELECT 1 FROM canonical_chunks c JOIN canonical_documents d ON d.doc_id=c.doc_id "
                    "WHERE d.library_id=? AND (c.text_clean LIKE ? OR c.text LIKE ?) LIMIT 1",
                    (library_id, like, like)).fetchone()
            else:  # 分库单文件布局：该库的 chunk 全在这个文件里
                hit = conn.execute(
                    "SELECT 1 FROM canonical_chunks WHERE (text_clean LIKE ? OR text LIKE ?) LIMIT 1",
                    (like, like)).fetchone()
        finally:
            conn.close()
        return bool(hit)


def default_sources() -> Sources:
    return Sources()


# ---------- 检查 ----------

def run_check(sources: Optional[Sources] = None) -> dict:
    """全库拒答题的前提断言。返回 {severity, checked, violations[], unknown[], error}。

    severity：ok=全部前提仍成立；warn=有前提失效（或全无前提可核）；
    error=存储不可访问，本晚未完成对账（不是违规）。
    """
    src = sources or default_sources()
    result: Dict[str, Any] = {"severity": _SEVERITY_OK, "checked": 0, "violations": [],
                              "unknown": [], "by_kind": {}, "error": ""}
    try:
        items = src.list_refusal_items()
    except Exception as exc:  # noqa: BLE001 读不到题面=环境问题
        result["severity"] = _SEVERITY_ERROR
        result["error"] = f"读取拒答题面失败: {type(exc).__name__}: {str(exc)[:160]}"
        return result

    memo: Dict[tuple, Optional[str]] = {}
    for item in items:
        premises = resolve_premises(item.get("gold") or {}, item.get("tags"))
        if not premises:
            result["unknown"].append({"dataset_id": item["dataset_id"],
                                      "question_id": item["question_id"]})
            continue
        result["checked"] += 1
        lib = item.get("library_id") or ""
        for p in premises:
            kind = str(p.get("kind") or "")
            result["by_kind"][kind] = result["by_kind"].get(kind, 0) + 1
            try:
                if kind == "doc_absent":
                    key = ("doc", lib, _paper_id(p.get("doc")) or str(p.get("doc")))
                    if key not in memo:
                        memo[key] = src.doc_present(lib, str(p.get("doc") or ""))
                    found = memo[key]
                    if found:
                        result["violations"].append({
                            "dataset_id": item["dataset_id"], "question_id": item["question_id"],
                            "kind": kind, "premise": p, "detail": f"源文档已入库（{found}）"})
                elif kind == "keyword_zero_hit":
                    for term in (p.get("terms") or []):
                        key = ("kw", lib, str(term))
                        if key not in memo:
                            memo[key] = "HIT" if src.keyword_present(lib, str(term)) else None
                        if memo[key]:
                            result["violations"].append({
                                "dataset_id": item["dataset_id"], "question_id": item["question_id"],
                                "kind": kind, "premise": p,
                                "detail": f"前提词「{term}」在库内已有命中"})
                else:
                    result["unknown"].append({"dataset_id": item["dataset_id"],
                                              "question_id": item["question_id"]})
            except Exception as exc:  # noqa: BLE001 存储不可访问：整晚降级，不判违规
                logger.warning("拒答前提对账存储不可访问: %s", exc)
                result["severity"] = _SEVERITY_ERROR
                result["error"] = f"存储不可访问: {type(exc).__name__}: {str(exc)[:160]}"
                return result
    if result["violations"]:
        result["severity"] = _SEVERITY_WARN
    elif result["checked"] == 0 and result["unknown"]:
        result["severity"] = _SEVERITY_WARN  # 有拒答题但全解析不出前提，说明元数据缺了
    return result


# ---------- 渲染 ----------

def render_line(result: Optional[dict]) -> str:
    """结论卡片里的一行摘要（与素材检查行并列）。没有拒答题可核时返回空串不占版面。"""
    if not result:
        return ""
    sev = result.get("severity")
    if sev == _SEVERITY_ERROR:
        return f"拒答前提对账：未完成（{result.get('error') or '存储不可访问'}）"
    if sev == _SEVERITY_OK and not result.get("checked") and not result.get("unknown"):
        return ""
    kinds = result.get("by_kind") or {}
    kind_txt = "、".join(f"{k} {v}" for k, v in kinds.items()) or "无"
    base = f"核 {result.get('checked', 0)} 题（{kind_txt}）"
    if result.get("violations"):
        names = "、".join(str(v.get("question_id")) for v in result["violations"][:3])
        line = f"拒答前提对账：**{len(result['violations'])} 题前提失效**（{names}…），标注需复核"
    elif sev == _SEVERITY_OK:
        line = f"拒答前提对账：ok（{base}，前提仍成立）"
    else:
        line = f"拒答前提对账：{base}"
    if result.get("unknown"):
        line += f"；另 {len(result['unknown'])} 题无前提可核"
    return line


def render_detail(result: Optional[dict], limit: int = 8) -> str:
    """独立告警消息正文：逐条列出失效题（上限 limit）。"""
    if not result:
        return ""
    lines = [render_line(result)]
    for v in (result.get("violations") or [])[:limit]:
        premise = v.get("premise") or {}
        target = premise.get("doc") or "、".join(premise.get("terms") or [])
        lines.append(f"- {v.get('dataset_id')} / {v.get('question_id')}：{v.get('detail')}"
                     f"（前提：{premise.get('kind')} {target}）")
    if len(result.get("violations") or []) > limit:
        lines.append(f"- …其余 {len(result['violations']) - limit} 条见归档 refusal_premise.json")
    for u in (result.get("unknown") or [])[:limit]:
        lines.append(f"- 无前提可核：{u.get('dataset_id')} / {u.get('question_id')}")
    return "\n".join(lines)
