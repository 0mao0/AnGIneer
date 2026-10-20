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
import os
import re
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

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
    updated_at  TEXT NOT NULL DEFAULT '',
    title_semantic    TEXT NOT NULL DEFAULT '',
    doc_type_semantic TEXT NOT NULL DEFAULT '',
    doc_date          TEXT NOT NULL DEFAULT '',
    date_source       TEXT NOT NULL DEFAULT 'none',
    date_confidence   TEXT NOT NULL DEFAULT 'none'
);
CREATE INDEX IF NOT EXISTS idx_doc_catalog_library ON doc_catalog(library_id);
CREATE INDEX IF NOT EXISTS idx_doc_catalog_matter ON doc_catalog(library_id, matter_id);
CREATE INDEX IF NOT EXISTS idx_doc_catalog_filename ON doc_catalog(library_id, filename);
"""

_CATALOG_EXTRA_COLUMNS = (
    ("title_semantic", "TEXT NOT NULL DEFAULT ''"),
    ("doc_type_semantic", "TEXT NOT NULL DEFAULT ''"),
    ("title_source", "TEXT NOT NULL DEFAULT ''"),
    ("doc_date", "TEXT NOT NULL DEFAULT ''"),
    ("date_source", "TEXT NOT NULL DEFAULT 'none'"),
    ("date_confidence", "TEXT NOT NULL DEFAULT 'none'"),
)

_CATALOG_DATE_COLUMNS = ("doc_date", "date_source", "date_confidence")

_WORD_RE = re.compile(r"[0-9A-Za-z_\u4e00-\u9fff]+")


def _connect(library_id: str) -> sqlite3.Connection:
    path = resolve_index_db_path(library_id)
    conn = sqlite3.connect(str(path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> set:
    try:
        return {row[1] for row in conn.execute(f"pragma table_info({table})")}
    except sqlite3.OperationalError:
        return set()


def ensure_catalog(conn: sqlite3.Connection) -> None:
    """幂等建表/补列：老表按需 ALTER，不重建、不丢数据。"""
    conn.executescript(_CATALOG_DDL)
    if has_catalog(conn):
        existing = _table_columns(conn, "doc_catalog")
        for name, ddl in _CATALOG_EXTRA_COLUMNS:
            if name not in existing:
                conn.execute(f"alter table doc_catalog add column {name} {ddl}")
        if set(_CATALOG_DATE_COLUMNS) <= _table_columns(conn, "doc_catalog"):
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_doc_catalog_date ON doc_catalog(library_id, doc_date)"
            )
    conn.commit()


def has_catalog(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "select 1 from sqlite_master where type='table' and name='doc_catalog'"
    ).fetchone()
    return row is not None


def catalog_has_dates(conn: sqlite3.Connection) -> bool:
    """目录是否已有日期三列（老库在建表前没有，需要先跑回填/ensure_catalog）。"""
    return has_catalog(conn) and set(_CATALOG_DATE_COLUMNS) <= _table_columns(conn, "doc_catalog")


def _tokens(query: str) -> List[str]:
    return [w for w in _WORD_RE.findall(query or "") if len(w) >= 2][:12]


def _fts_match(tokens: List[str], *, phrase: bool) -> Optional[str]:
    if not tokens:
        return None
    if phrase and len(tokens) > 1:
        return '"' + " ".join(tokens) + '"'
    return " ".join(tokens)


def _display_title(filename: str, title_semantic: str) -> str:
    """展示名：文件名语义化时用文件名；纯编号/UUID 时退回首屏标题。"""
    name = str(filename or "")
    stem = re.sub(r"\.[A-Za-z0-9]{1,6}$", "", name)
    if title_semantic and not re.search(r"[A-Za-z\u4e00-\u9fff]{3,}", stem):
        return str(title_semantic)
    return name or str(title_semantic or "")


def _catalog_map(
    conn: sqlite3.Connection,
    library_id: str,
    doc_ids: List[str],
    *,
    with_dates: bool = False,
) -> Dict[str, Dict[str, Any]]:
    if not doc_ids or not has_catalog(conn):
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    date_cols = ", doc_date, date_source, date_confidence" if with_dates else ""
    for start in range(0, len(doc_ids), 400):
        chunk = doc_ids[start : start + 400]
        marks = ",".join("?" * len(chunk))
        rows = conn.execute(
            f"select doc_id, matter_id, folder, rel_path, filename, title_semantic, doc_type_semantic"
            f"{date_cols} "
            f"from doc_catalog where library_id=? and doc_id in ({marks})",
            [library_id, *chunk],
        )
        for row in rows:
            item = dict(row)
            item["display_title"] = _display_title(row["filename"], row["title_semantic"])
            out[row["doc_id"]] = item
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
    like = " or ".join("(filename like ? or rel_path like ? or title_semantic like ?)" for _ in tokens)
    params: List[Any] = [library_id]
    for token in tokens:
        params += [f"%{token}%", f"%{token}%", f"%{token}%"]
    rows = conn.execute(
        f"select doc_id, filename, rel_path, title_semantic from doc_catalog "
        f"where library_id=? and ({like}) limit ?",
        [*params, max(limit * 8, 400)],
    )
    phrase = " ".join(tokens).lower()
    min_tokens = 2 if len(tokens) >= 2 else 1
    out: Dict[str, Any] = {}
    for row in rows:
        hay = f"{row['filename']} {row['rel_path']} {row['title_semantic'] or ''}".lower()
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
    """目录谓词：按「文件名 / 路径 / 语义标题」短语（AND）筛选，返回 doc_id → 展示名。

    这是枚举题最确定的通道：文档类型写在文件名里（second-request-*、hsr-withdrawal-*），
    或写在首屏标题里（arXiv 编号文件也有论文标题）。直接按目录过滤比 FTS 排序精确得多
    （题 001 实测：["second request"] 命中 9 篇、24 张卡、真值 6/6）。
    每个短语归一后要求逐词出现；多短语之间是 AND（调用方可用多次调用表达 OR）。
    """
    if not phrases or not has_catalog(conn):
        return {}
    clauses: List[str] = []
    params: List[Any] = [library_id]
    normalized = [_norm_name(p) for p in phrases if _norm_name(p)]
    for phrase in normalized:
        for token in phrase.split():
            clauses.append("(filename like ? or rel_path like ? or title_semantic like ?)")
            params += [f"%{token}%", f"%{token}%", f"%{token}%"]
    if not clauses:
        return {}
    where = " and ".join(clauses)
    if doc_type:
        want = str(doc_type).lower().lstrip(".")
        where += " and (doc_type=? or doc_type_semantic=?)"
        params += [want, want]
    try:
        rows = conn.execute(
            f"select doc_id, filename, rel_path, title_semantic from doc_catalog "
            f"where library_id=? and ({where}) limit ?",
            [*params, limit],
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    out: Dict[str, str] = {}
    norm_tokens = [token for phrase in normalized for token in phrase.split()]
    for row in rows:
        haystack = _norm_name(f"{row['filename']} {row['rel_path']} {row['title_semantic'] or ''}")
        # 逐词检查而不是整串连续匹配：标题里常有停用词插入
        #（"Conspiracy Theories on Telegram" 对 "conspiracy theories telegram"）
        if all(token in haystack for token in norm_tokens):
            out[row["doc_id"]] = row["filename"] or row["title_semantic"] or row["doc_id"]
    return out


# 文档类型规则（先规则后模型：覆盖法律/工程规范/学术语料，未知归 other）
# 顺序很重要：标准号前缀 → 具体文书 → 政策 → 规范词 → 报告 → 论文 → 其他。
_STANDARD_CODE_RE = re.compile(
    r"^\s*(?:GB(?:/T|_T)?|JTS?|JTG|JT[_/]T|DB\d*|SL|DL|CJJ|TB|HG|SH|SY|NB|"
    r"ISO|IEC|EN|ASTM|API|BS|DIN|ANSI)\s*[_\-/]?\s*\d",
    re.I,
)
_POLICY_KEYS = ("制度", "管理办法", "办法", "实施细则", "细则", "通知", "意见", "方案", "政策")
_STANDARD_KEYS = ("规范", "标准", "规程", "规定", "导则", "技术要求", "技术条件", "图集", "条文")
_REPORT_KEYS = (
    "检测报告", "评估报告", "试验报告", "监测报告", "审计报告", "调查报告", "研究报告",
    "年度报告", "白皮书", "bulletin", "report",
)
_REPORT_EXCLUDE_RE = re.compile(r"报告(?:编制|格式|模板|导则)")
# 法律/法规：中华人民共和国…法、…条例、…法典；英文 Act/Statute。
# 不用裸「法」匹配（会误伤「方法/算法」），要求「法」后是括号/结尾/空白。
_LAW_RE = re.compile(
    r"(?:中华人民共和国[^，。；\s]{0,30}法(?:[（(]|$|\s|\.))|(?:[^方法算]法(?:[（(]|$|\s|\.))|(?:条例|法典)(?:[（(]|$|\s|\.)"
    r"|(?:^|\s)(?:act|statute)(?:\s|$|\.)",
    re.I,
)
_DOC_TYPE_RULES = (
    ("memo", ("memo", "memorandum", "备忘", "纪要")),
    ("agreement", ("agreement", "contract", "spa", "credit agreement", "lease", "协议", "合同")),
    ("letter", ("letter", "email", "eml", "函", "信")),
    ("order", ("order", "judgment", "decree", "opinion", "裁定", "判决")),
    ("filing", ("filing", "notification", "form", "hsr", "申报", "备案")),
    ("invoice", ("invoice", "billing", "发票", "账单")),
    ("statement", ("statement", "certificate", "证明", "证书")),
)


def classify_doc_type(filename: str, title: str = "") -> str:
    """规则分类。标准号前缀优先：`GB 17380 …规定` 是规范，不是「政策/规定」。"""
    hay = f"{filename} {title}".strip()
    low = hay.lower()
    if _STANDARD_CODE_RE.match(str(filename or "").strip()) or _STANDARD_CODE_RE.match(str(title or "").strip()):
        return "standard"
    for name, keys in _DOC_TYPE_RULES:
        if any(k.lower() in low for k in keys):
            return name
    if any(k in hay for k in _POLICY_KEYS):
        return "policy"
    if _LAW_RE.search(hay):
        return "law"
    if any(k in hay for k in _STANDARD_KEYS):
        return "standard"
    if any(k in low for k in _REPORT_KEYS) and not _REPORT_EXCLUDE_RE.search(hay):
        return "report"
    if any(k in low for k in ("abstract", "arxiv", "论文", "proceedings", "journal", "thesis", "et al.")):
        return "paper"
    return "other"


def backfill_semantic_fields(conn: sqlite3.Connection, library_id: str, batch: int = 500) -> Dict[str, int]:
    """从 doc_blocks 首屏 title 块物化 title_semantic + doc_type_semantic（不重跑解析）。

    - title：第一页最早的 title 块（title_path 末段），没有则用文件名去扩展名；
    - doc_type_semantic：classify_doc_type(filename, title)。
    """
    ensure_catalog(conn)
    if conn.row_factory is None:  # 回填脚本的连接可能没设 Row 工厂
        conn.row_factory = sqlite3.Row
    total = conn.execute("select count(*) from doc_catalog where library_id=?", (library_id,)).fetchone()[0]
    rows = conn.execute("select doc_id, filename from doc_catalog where library_id=?", (library_id,)).fetchall()
    names = {r["doc_id"]: (r["filename"] or "") for r in rows}
    titles: Dict[str, str] = {}
    try:
        for r in conn.execute(
            "select doc_id, title_path from ("
            "  select doc_id, title_path, row_number() over (partition by doc_id order by page_idx, block_seq) rn"
            "  from doc_blocks where block_type='title' and page_idx=0 and length(trim(title_path))>1"
            ") where rn=1"
        ):
            path = str(r["title_path"] or "").strip()
            titles[r["doc_id"]] = path.split(" / ")[-1].strip() or path
    except sqlite3.OperationalError:
        titles = {}
    abstract_docs: set[str] = set()
    try:
        abstract_docs = {
            r[0]
            for r in conn.execute(
                "select distinct doc_id from doc_blocks where page_idx=0 and block_type='title' "
                "and lower(title_path) like '%abstract%'"
            )
        }
    except sqlite3.OperationalError:
        abstract_docs = set()
    updates = []
    for doc_id, filename in names.items():
        stem = re.sub(r"\.[A-Za-z0-9]{1,6}$", "", filename or "")
        block_title = titles.get(doc_id) or ""
        title = block_title or stem
        dtype = classify_doc_type(filename, title)
        if dtype == "other" and doc_id in abstract_docs:
            dtype = "paper"  # 首屏有 Abstract 标题块：学术论文（编号文件名也能识别）
        updates.append((title, dtype, "block" if block_title else "filename", library_id, doc_id))
    conn.executemany(
        "update doc_catalog set title_semantic=?, doc_type_semantic=?, title_source=? "
        "where library_id=? and doc_id=?",
        updates,
    )
    conn.commit()
    with_title = sum(1 for u in updates if u[0])
    typed = sum(1 for u in updates if u[1] != "other")
    return {"total": total, "with_title": with_title, "typed": typed, "titles_from_blocks": len(titles)}


def catalog_write_enabled() -> bool:
    """目录写入总开关（ANGINEER_CATALOG_WRITE，默认开）。

    关掉后上传不再写 doc_catalog、解析完成不再刷新语义；检索侧读不到目录行，
    自动退回内容检索，行为与改造前一致。
    """
    return os.getenv("ANGINEER_CATALOG_WRITE", "1").strip().lower() not in ("0", "false", "no", "off")


# ---------------------------------------------------------------------------
# 文档日期（时间维度）：正文首屏 > 文件名 > 源文件 mtime，抽不到为空
# ---------------------------------------------------------------------------

_MONTH_DATE = r"([A-Z][a-z]{2,8}\.?\s+\d{1,2},\s+\d{4})"
_TEXT_DATE_PATTERNS = (
    # "Dated as of July 16, 2024" 权重最高：合同/协议/函件的落款句式
    re.compile(r"dated\s+as\s+of\s+" + _MONTH_DATE, re.I),
    re.compile(r"dated\s*[:\-]?\s*" + _MONTH_DATE, re.I),
    re.compile(r"as\s+of\s+" + _MONTH_DATE, re.I),
)
_ISO_DATE_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})-(\d{1,2})-(\d{1,2})(?!\d)")
_FILENAME_DATE_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})[-_.]?(\d{2})[-_.]?(\d{2})(?!\d)")
# 中文日期：2024年7月16日 / 2024 年 7 月；只有年月时按当月 1 日落库并标 low
_CN_DATE_RE = re.compile(r"((?:19|20)\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
_CN_MONTH_RE = re.compile(r"((?:19|20)\d{2})\s*年\s*(\d{1,2})\s*月")
_CN_YEAR_RE = re.compile(r"((?:19|20)\d{2})\s*年")
_YEAR_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
_YEAR_MIN = 1900
_YEAR_MAX = datetime.now().year + 1
_FUTURE_SLACK_DAYS = 366

DATE_SOURCES = ("text", "filename", "mtime", "none")
DATE_CONFIDENCES = ("high", "medium", "low", "none")


def _plausible(iso: Optional[str]) -> Optional[str]:
    """日期合理性闸门：超出 [1900, 今天+366 天] 的一律丢弃（不猜）。

    法律/表格语料实测：正文里的孤立年份常来自引证页码（"F.3d 2094"）、
    表格单元格（"2026 Standard"），xlsx 还会把文件属性里的时间戳写进首屏。
    这类年份一旦参与排序，会把「最新/最近」题直接带偏，所以只收合理区间内的日期。
    """
    if not iso:
        return None
    try:
        value = date.fromisoformat(iso)
    except ValueError:
        return None
    if value.year < _YEAR_MIN:
        return None
    if value > date.today() + timedelta(days=_FUTURE_SLACK_DAYS):
        return None
    return value.isoformat()


def _iso_from_parts(year: Any, month: Any, day: Any) -> Optional[str]:
    try:
        y, m, d = int(year), int(month), int(day)
    except (TypeError, ValueError):
        return None
    if not (_YEAR_MIN <= y <= _YEAR_MAX):
        return None
    try:
        return _plausible(date(y, m, d).isoformat())
    except ValueError:
        return None


def _month_date_to_iso(raw: str) -> Optional[str]:
    cleaned = re.sub(r"\s+", " ", str(raw or "").replace(".", "")).strip()
    if not cleaned:
        return None
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return _plausible(datetime.strptime(cleaned, fmt).date().isoformat())
        except ValueError:
            continue
    return None


def _year_only_iso(year: Any) -> Optional[str]:
    """只有年份时按 YYYY-07-01 落库（low）；未来年份不可信，返回空。"""
    try:
        value = int(year)
    except (TypeError, ValueError):
        return None
    if value < _YEAR_MIN or value > date.today().year:
        return None
    return f"{value}-07-01"


def extract_date_from_text(text: str) -> Tuple[str, str, str]:
    """从首屏正文抽日期，返回 (iso_date, source, confidence)。

    优先 "dated as of"/"dated:" 句式与完整日期（high）；中文「2024年」这类明确的
    年份上下文按 YYYY-07-01 落库并标 low。**不抽英文孤立年份**：法律语料里
    "F.3d 2094" / "2026 Standard" 这类数字会污染时间排序（实测 5283/9009 条 low 里
    大量是这种噪声），宁可退回文件名/mtime。
    """
    head = str(text or "")[:4000]
    if not head.strip():
        return ("", "none", "none")
    for pattern in _TEXT_DATE_PATTERNS:
        match = pattern.search(head)
        if not match:
            continue
        iso = _month_date_to_iso(match.group(1))
        if iso:
            return (iso, "text", "high")
    match = _CN_DATE_RE.search(head)
    if match:
        iso = _iso_from_parts(*match.groups())
        if iso:
            return (iso, "text", "high")
    match = _ISO_DATE_RE.search(head)
    if match:
        iso = _iso_from_parts(*match.groups())
        if iso:
            return (iso, "text", "high")
    match = _CN_MONTH_RE.search(head)
    if match:
        year, month = int(match.group(1)), int(match.group(2))
        if 1 <= month <= 12 and year <= date.today().year:
            return (f"{year}-{month:02d}-01", "text", "low")
    match = _CN_YEAR_RE.search(head)
    if match:
        iso = _year_only_iso(match.group(1))
        if iso:
            return (iso, "text", "low")
    return ("", "none", "none")


def extract_date_from_filename(name: str) -> Tuple[str, str, str]:
    """从文件名抽日期：完整日期为 medium，只有年份/年月为 low。"""
    stem = str(name or "")
    if not stem:
        return ("", "none", "none")
    match = _FILENAME_DATE_RE.search(stem)
    if match:
        iso = _iso_from_parts(*match.groups())
        if iso:
            return (iso, "filename", "medium")
    match = _CN_DATE_RE.search(stem)
    if match:
        iso = _iso_from_parts(*match.groups())
        if iso:
            return (iso, "filename", "medium")
    match = _CN_MONTH_RE.search(stem)
    if match:
        year, month = int(match.group(1)), int(match.group(2))
        if 1 <= month <= 12 and year <= date.today().year:
            return (f"{year}-{month:02d}-01", "filename", "low")
    match = _YEAR_RE.search(stem)
    if match:
        iso = _year_only_iso(match.group(1))
        if iso:
            return (iso, "filename", "low")
    return ("", "none", "none")


def _first_page_texts(conn: sqlite3.Connection, doc_ids: List[str], budget: int = 4000) -> Dict[str, str]:
    """批量取每篇第一页文本（page_idx=0 的 blocks 顺序拼接，≤ budget 字符）。

    doc_blocks 不存在或列缺失时返回空表（回填照样能退化到文件名/mtime）。
    """
    out: Dict[str, str] = {}
    for start in range(0, len(doc_ids), 400):
        chunk = doc_ids[start : start + 400]
        marks = ",".join("?" * len(chunk))
        try:
            rows = conn.execute(
                f"select doc_id, plain_text from doc_blocks where doc_id in ({marks}) "
                "and page_idx=0 order by doc_id, block_seq",
                chunk,
            )
        except sqlite3.OperationalError:
            return out
        for row in rows:
            piece = str(row["plain_text"] or "").strip()
            if not piece:
                continue
            current = out.get(row["doc_id"], "")
            if len(current) >= budget:
                continue
            joined = f"{current}\n{piece}" if current else piece
            out[row["doc_id"]] = joined[:budget]
    return out


def _source_mtime_iso(library_id: str, doc_id: str) -> str:
    """源文件 mtime（low 兜底）。文件不存在/不可读返回空串——不猜日期。"""
    try:
        from docs_core.step01_source_prep.source_prep import resolve_source_file

        path = resolve_source_file(library_id, doc_id)
        if not path:
            return ""
        stamp = os.path.getmtime(path)
        if stamp <= 0:
            return ""
        return datetime.fromtimestamp(stamp).date().isoformat()
    except Exception:  # noqa: BLE001 —— mtime 只是兜底，任何失败都退化为无日期
        return ""


def backfill_doc_dates(
    library_id: str,
    *,
    limit: Optional[int] = None,
    conn: Optional[sqlite3.Connection] = None,
    mtime_resolver: Any = None,
) -> Dict[str, Any]:
    """回填 doc_catalog 的 doc_date/date_source/date_confidence（不重跑解析）。

    优先级：正文首屏日期（high）> 文件名完整日期（medium）> 仅年份（low）>
    源文件 mtime（low）> 空（none）。幂等：只 UPDATE 值有变化的行。
    """
    own = conn is None
    conn = conn or _connect(library_id)
    try:
        ensure_catalog(conn)
        if conn.row_factory is None:
            conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "select doc_id, filename, rel_path, doc_date, date_source, date_confidence "
            "from doc_catalog where library_id=? order by doc_id",
            (library_id,),
        ).fetchall()
        if limit is not None and limit >= 0:
            rows = rows[:limit]
        texts = _first_page_texts(conn, [r["doc_id"] for r in rows]) if rows else {}
        resolver = mtime_resolver or _source_mtime_iso
        by_source = {name: 0 for name in DATE_SOURCES}
        by_confidence = {name: 0 for name in DATE_CONFIDENCES}
        updates: List[Tuple[str, str, str, str, str]] = []
        for row in rows:
            doc_id = row["doc_id"]
            name = row["filename"] or os.path.basename(str(row["rel_path"] or ""))
            iso, source, confidence = extract_date_from_text(texts.get(doc_id, ""))
            if not iso:
                iso, source, confidence = extract_date_from_filename(name)
            if not iso:
                iso = str(resolver(library_id, doc_id) or "")
                source, confidence = ("mtime", "low") if iso else ("none", "none")
            by_source[source] = by_source.get(source, 0) + 1
            by_confidence[confidence] = by_confidence.get(confidence, 0) + 1
            if (
                iso != (row["doc_date"] or "")
                or source != (row["date_source"] or "none")
                or confidence != (row["date_confidence"] or "none")
            ):
                updates.append((iso, source, confidence, library_id, doc_id))
        if updates:
            conn.executemany(
                "update doc_catalog set doc_date=?, date_source=?, date_confidence=? "
                "where library_id=? and doc_id=?",
                updates,
            )
            conn.commit()
        return {
            "library_id": library_id,
            "total": len(rows),
            "with_date": len(rows) - by_confidence.get("none", 0),
            "updated": len(updates),
            "by_source": by_source,
            "by_confidence": by_confidence,
        }
    finally:
        if own:
            conn.close()


def catalog_date_coverage(conn: sqlite3.Connection, library_id: str) -> Dict[str, Any]:
    """日期覆盖分布（施工/验收观测用）：按 source、confidence 计数与日期区间。"""
    if not catalog_has_dates(conn):
        return {"catalog": has_catalog(conn), "dates": False, "total": 0, "with_date": 0}
    total = int(
        conn.execute("select count(*) from doc_catalog where library_id=?", (library_id,)).fetchone()[0]
    )
    row = conn.execute(
        "select sum(case when doc_date<>'' then 1 else 0 end) as dated, "
        "min(case when doc_date<>'' then doc_date end) as dmin, "
        "max(case when doc_date<>'' then doc_date end) as dmax "
        "from doc_catalog where library_id=?",
        (library_id,),
    ).fetchone()
    by_source = {
        str(r[0] or "none"): int(r[1])
        for r in conn.execute(
            "select date_source, count(*) from doc_catalog where library_id=? group by date_source",
            (library_id,),
        )
    }
    by_confidence = {
        str(r[0] or "none"): int(r[1])
        for r in conn.execute(
            "select date_confidence, count(*) from doc_catalog where library_id=? group by date_confidence",
            (library_id,),
        )
    }
    dated = int(row["dated"] or 0)
    return {
        "catalog": True,
        "dates": True,
        "total": total,
        "with_date": dated,
        "coverage": round(dated / total, 3) if total else 0.0,
        "date_min": row["dmin"] or "",
        "date_max": row["dmax"] or "",
        "by_source": by_source,
        "by_confidence": by_confidence,
    }


def upsert_catalog_doc(
    *,
    library_id: str,
    doc_id: str,
    filename: str,
    rel_path: str = "",
    matter_id: str = "",
    folder: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    """入库时写一行目录（幂等）。

    title/type 先用文件名；解析完成后由 backfill_semantic_fields 用首屏标题刷新
    （title_source='block' 的行不会被这里覆盖）。
    """
    own = conn is None
    conn = conn or _connect(library_id)
    try:
        ensure_catalog(conn)
        if conn.row_factory is None:
            conn.row_factory = sqlite3.Row
        folder_name = (
            folder if folder is not None
            else (str(rel_path).rsplit("/", 1)[0] if "/" in str(rel_path) else "")
        )
        stem = re.sub(r"\.[A-Za-z0-9]{1,6}$", "", filename or "")
        title = stem
        dtype = classify_doc_type(filename, title)
        conn.execute(
            "insert into doc_catalog(doc_id, library_id, matter_id, folder, rel_path, filename, "
            "doc_type, source, updated_at, title_semantic, doc_type_semantic, title_source) "
            "values(?,?,?,?,?,?,?,?,?,?,?,'filename') "
            "on conflict(doc_id) do update set filename=excluded.filename, rel_path=excluded.rel_path, "
            "folder=excluded.folder, "
            "title_semantic=case when doc_catalog.title_source='block' then doc_catalog.title_semantic "
            "else excluded.title_semantic end, "
            "doc_type_semantic=case when doc_catalog.title_source='block' then doc_catalog.doc_type_semantic "
            "else excluded.doc_type_semantic end",
            (doc_id, library_id, matter_id or "", folder_name, rel_path or "", filename or "",
             (str(filename).rsplit(".", 1)[-1].lower() if "." in str(filename) else ""), "upload",
             "", title, dtype),
        )
        conn.commit()
        kind = "case" if matter_id else ("folder" if folder_name else "doc")
        return {"doc_id": doc_id, "group_kind": kind, "title": title, "doc_type": dtype}
    finally:
        if own:
            conn.close()


def _doc_semantic(conn: sqlite3.Connection, doc_id: str, filename: str) -> tuple[str, str, str]:
    """单篇语义标题/类型：首屏 title 块优先，Abstract 判论文，否则文件名。"""
    block_title = ""
    try:
        row = conn.execute(
            "select title_path from doc_blocks where doc_id=? and page_idx=0 and block_type='title' "
            "and length(trim(title_path))>1 order by block_seq limit 1",
            (doc_id,),
        ).fetchone()
        if row and row[0]:
            path = str(row[0]).strip()
            block_title = path.split(" / ")[-1].strip() or path
    except sqlite3.OperationalError:
        block_title = ""
    stem = re.sub(r"\.[A-Za-z0-9]{1,6}$", "", filename or "")
    title = block_title or stem
    dtype = classify_doc_type(filename, title)
    if dtype == "other":
        try:
            hit = conn.execute(
                "select 1 from doc_blocks where doc_id=? and page_idx=0 and block_type='title' "
                "and lower(title_path) like '%abstract%' limit 1",
                (doc_id,),
            ).fetchone()
            if hit:
                dtype = "paper"
        except sqlite3.OperationalError:
            pass
    return title, dtype, ("block" if block_title else "filename")


def refresh_doc_semantics(library_id: str, doc_id: str) -> Dict[str, Any]:
    """解析完成后刷新单篇的语义标题/类型（目录行不存在则跳过，由回填脚本兜底）。"""
    conn = _connect(library_id)
    try:
        ensure_catalog(conn)
        if conn.row_factory is None:
            conn.row_factory = sqlite3.Row
        row = conn.execute(
            "select filename from doc_catalog where library_id=? and doc_id=?", (library_id, doc_id)
        ).fetchone()
        if row is None:
            return {"doc_id": doc_id, "skipped": "no catalog row"}
        title, dtype, source = _doc_semantic(conn, doc_id, row["filename"] or "")
        conn.execute(
            "update doc_catalog set title_semantic=?, doc_type_semantic=?, title_source=? "
            "where library_id=? and doc_id=?",
            (title, dtype, source, library_id, doc_id),
        )
        conn.commit()
        return {"doc_id": doc_id, "title": title, "doc_type": dtype, "title_source": source}
    finally:
        conn.close()


def catalog_semantic_coverage(conn: sqlite3.Connection, library_id: str) -> Dict[str, Any]:
    """目录质量：文件名语义率、首屏标题率、类型覆盖率，供预取门禁决定是否启用目录谓词。

    - filename_semantic_rate：文件名主干是否含 3 个以上字母/汉字（编号/UUID 文件为低）；
    - title_block_rate：title_semantic 是否来自正文首屏标题（而非文件名回退）；
    - type_rate：doc_type_semantic 非 other 的占比。
    """
    if not has_catalog(conn):
        return {"catalog": False, "filename_semantic_rate": 0.0, "title_block_rate": 0.0, "type_rate": 0.0}
    row = conn.execute(
        "select count(*) as n,"
        " sum(case when title_source='block' then 1 else 0 end) as block_n,"
        " sum(case when doc_type_semantic<>'' and doc_type_semantic<>'other' then 1 else 0 end) as type_n"
        " from doc_catalog where library_id=?",
        (library_id,),
    ).fetchone()
    n = int(row["n"] or 0)
    sample = conn.execute(
        "select filename from doc_catalog where library_id=? limit 500", (library_id,)
    ).fetchall()
    sem = 0
    for r in sample:
        stem = re.sub(r"\.[A-Za-z0-9]{1,6}$", "", r[0] or "")
        if re.search(r"[A-Za-z\u4e00-\u9fff]{3,}", stem):
            sem += 1
    return {
        "catalog": True,
        "total": n,
        "filename_semantic_rate": round(sem / len(sample), 3) if sample else 0.0,
        "title_block_rate": round((row["block_n"] or 0) / n, 3) if n else 0.0,
        "type_rate": round((row["type_n"] or 0) / n, 3) if n else 0.0,
    }


def catalog_predicate_usable(library_id: str, threshold: float = 0.3) -> bool:
    """目录谓词门禁：文件名语义率或首屏标题率 ≥ 阈值才建议启用。"""
    conn = _connect(library_id)
    try:
        cov = catalog_semantic_coverage(conn, library_id)
    finally:
        conn.close()
    if not cov.get("catalog"):
        return False
    return (
        cov.get("filename_semantic_rate", 0) >= threshold
        or cov.get("title_block_rate", 0) >= threshold
    )


def _group_identity(matter_id: str, folder: str, doc_id: str) -> Dict[str, str]:
    """分组的唯一身份：matter（case）> folder > 单篇（doc）。"""
    matter = str(matter_id or "").strip()
    if matter:
        return {"group_id": matter, "group_kind": "case"}
    folder_name = str(folder or "").strip()
    if folder_name:
        return {"group_id": f"folder:{folder_name}", "group_kind": "folder"}
    return {"group_id": f"doc:{doc_id}", "group_kind": "doc"}


def list_matters(library_id: str, limit: int = 300) -> Dict[str, Any]:
    """matter 清单（等价于对 DMS 做一次 ls）：matter_id + 文档数 + 代表文件名。

    没有 matter 元数据的库（普通上传）matter_id 为空，不返回假 matter；
    只报 documents 总数，调用方改走 docs 视图。
    """
    conn = _connect(library_id)
    try:
        if not has_catalog(conn):
            return {"catalog": False, "total": 0, "documents": 0, "matters": []}
        rows = conn.execute(
            "select matter_id, count(*) as n, min(filename) as sample, max(folder) as folder "
            "from doc_catalog where library_id=? and matter_id<>'' "
            "group by matter_id order by matter_id limit ?",
            (library_id, max(1, min(int(limit or 300), 500))),
        ).fetchall()
        total = conn.execute(
            "select count(distinct matter_id) from doc_catalog where library_id=? and matter_id<>''",
            (library_id,),
        ).fetchone()[0]
        documents = conn.execute(
            "select count(*) from doc_catalog where library_id=?", (library_id,)
        ).fetchone()[0]
        folder_groups = conn.execute(
            "select count(distinct folder) from doc_catalog where library_id=? and matter_id='' and folder<>''",
            (library_id,),
        ).fetchone()[0]
        doc_groups = conn.execute(
            "select count(*) from doc_catalog where library_id=? and matter_id='' and folder=''",
            (library_id,),
        ).fetchone()[0]
    finally:
        conn.close()
    return {
        "catalog": True,
        "total": int(total),
        "documents": int(documents),
        "group_kinds": {"case": int(total), "folder": int(folder_groups), "doc": int(doc_groups)},
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


def _clean_iso_date(value: Optional[str]) -> Optional[str]:
    """校验 YYYY-MM-DD；非法值返回 None（不猜，调用方把非法值回显给模型）。"""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def _date_ord(value: str) -> int:
    try:
        return date.fromisoformat(str(value or "")[:10]).toordinal()
    except ValueError:
        return 0


def _usable_doc_date(cat: Optional[Dict[str, Any]]) -> Tuple[str, str]:
    """可作为「文档日期」使用的值：text/filename 来源算；mtime 只是文件落盘时间，不算。

    mtime 会随拷贝/迁移变化（计划风险表），Harvey 语料实测 57% 的行只有 mtime，
    且集中在入库当天——若让它参与排序/过滤，「最新」题会被入库时间淹没。
    """
    cat = cat or {}
    value = str(cat.get("doc_date") or "")
    source = str(cat.get("date_source") or "none")
    if not value or source in ("", "none", "mtime"):
        return ("", source or "none")
    return (value, source)


def search_documents(
    *,
    library_id: str = "default",
    query: str,
    limit: int = 40,
    per_matter: int = 2,
    filename_contains: Optional[List[str]] = None,
    doc_type: Optional[str] = None,
    sort_by: Optional[str] = None,
    date_after: Optional[str] = None,
    date_before: Optional[str] = None,
    entity_contains: Optional[str] = None,
) -> Dict[str, Any]:
    """文档级检索：返回按 matter 归并的候选清单（枚举视图）。

    filename_contains：目录谓词（短语列表，AND）——按文件名/路径过滤，高于 FTS 的确定性信号；
    doc_type：限定扩展名（xlsx/docx/pdf…）。两者只在有 doc_catalog 的库生效。

    sort_by：None（默认，按相关性，行为与加日期前逐字节一致）/ "date_desc" / "date_asc"；
    date_after/date_before：YYYY-MM-DD 区间过滤，显式过滤时**排除无日期文档**（不猜）。

    entity_contains：实体/客户/案件名——先找出提到它的文档，再把这些文档所属的
    matter/group 作为检索范围（「Lumos 最近一份信贷协议」= entity + filename + date_desc 一次调用）。
    """
    limit = max(1, min(int(limit or 40), MAX_DOCS))
    per_matter = max(1, min(int(per_matter or 2), 10))
    tokens = _tokens(query)
    entity_name = str(entity_contains or "").strip()
    if not tokens and not filename_contains and not entity_name:
        return {"error": "缺少有效检索词", "query": query}

    invalid: List[str] = []
    sort_by = str(sort_by or "").strip() or None
    if sort_by not in (None, "date_desc", "date_asc"):
        invalid.append(f"sort_by={sort_by}")
        sort_by = None
    raw_after, raw_before = str(date_after or "").strip(), str(date_before or "").strip()
    after = _clean_iso_date(raw_after)
    before = _clean_iso_date(raw_before)
    if raw_after and not after:
        invalid.append(f"date_after={raw_after}")
    if raw_before and not before:
        invalid.append(f"date_before={raw_before}")
    # 非法参数也算「用过日期通道」：要在结果里回显 invalid，而不是静默当成没传
    date_mode = bool(sort_by or after or before or raw_after or raw_before)

    conn = _connect(library_id)
    catalog: Dict[str, Dict[str, Any]] = {}
    docs: List[Dict[str, Any]] = []
    matter_list: List[Dict[str, Any]] = []
    groups: Dict[str, Dict[str, Any]] = {}
    candidates: Dict[str, Dict[str, Any]] = {}
    catalog_docs: Dict[str, str] = {}
    date_warning = ""
    entity_groups: set = set()
    entity_rows: List[Dict[str, Any]] = []
    try:
        if date_mode:
            # 日期排序/过滤依赖目录三列；无目录直接报错（不建表、不静默返回全空）
            if not has_catalog(conn):
                return {
                    "error": "本库没有 doc_catalog（未建目录），无法按日期排序/过滤",
                    "query": query,
                    "library_id": library_id,
                }
            try:
                ensure_catalog(conn)
            except sqlite3.Error as exc:  # noqa: BLE001
                date_warning = f"目录补列失败: {exc}"
            if not catalog_has_dates(conn):
                return {
                    "error": "本库没有 doc_catalog 日期列，无法按日期排序/过滤；请先运行 "
                    "scripts/backfill_doc_dates.py 回填",
                    "query": query,
                    "library_id": library_id,
                }

        if entity_name:
            # 第一步：实体定位——先找提到实体的文档，再把它们所属 group 作为检索范围
            ent_tokens = _tokens(entity_name)
            if not ent_tokens:
                return {"error": f"entity_contains 无有效检索词: {entity_name!r}", "query": query}
            if not has_catalog(conn):
                return {"error": "本库没有 doc_catalog，无法按实体限定范围", "query": query}
            entity_rows = _text_hits(conn, library_id, ent_tokens, max(limit, 60), include_loose=False)
            if len(entity_rows) < 3:
                entity_rows = _text_hits(
                    conn, library_id, ent_tokens, max(limit, 60), include_loose=True
                )
            ent_cat = _catalog_map(conn, library_id, [r["doc_id"] for r in entity_rows])
            for row in entity_rows:
                cat = ent_cat.get(row["doc_id"]) or {}
                ident = _group_identity(cat.get("matter_id", ""), cat.get("folder", ""), row["doc_id"])
                entity_groups.add(ident["group_id"])
            if not entity_groups:
                return {
                    "error": f"未找到提到「{entity_name}」的文档（实体未命中，换关键词再试）",
                    "query": query,
                    "library_id": library_id,
                }

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
        if not tokens and not filename_contains and entity_rows:
            # 只给实体：返回该实体的全部文档，按 group 归并（配合 sort_by 即可看「这家的最新文件」）
            candidates = {r["doc_id"]: r for r in entity_rows}

        if entity_name:
            catalog_ids = list(candidates)
        else:
            catalog_ids = list(candidates) if date_mode else list(candidates)[: max(limit * 8, 400)]
        catalog = _catalog_map(conn, library_id, catalog_ids, with_dates=date_mode)
        if date_mode and candidates and not catalog:
            date_warning = "候选文档没有目录行，日期均为空：排序无效、区间过滤会排除全部候选"

        if entity_groups:
            # 第二步：范围收窄——只保留实体所属 group 内的候选
            kept_entity: Dict[str, Dict[str, Any]] = {}
            for doc_id, entry in candidates.items():
                cat = catalog.get(doc_id) or {}
                ident = _group_identity(cat.get("matter_id", ""), cat.get("folder", ""), doc_id)
                if ident["group_id"] in entity_groups:
                    kept_entity[doc_id] = entry
            candidates = kept_entity
            if not candidates:
                return {
                    "error": f"实体「{entity_name}」命中 {len(entity_groups)} 个分组，但没有符合其余条件的文档",
                    "query": query,
                    "library_id": library_id,
                }
        if after or before:
            # 显式区间过滤：无「可用的文档日期」的候选一律排除，不做猜测。
            # mtime 只是源文件落盘时间（拷贝/迁移会变），不算文档日期，故也排除。
            kept: Dict[str, Dict[str, Any]] = {}
            for doc_id, entry in candidates.items():
                value, source = _usable_doc_date(catalog.get(doc_id))
                if not value:
                    continue
                if after and value < after:
                    continue
                if before and value > before:
                    continue
                kept[doc_id] = entry
            candidates = kept
        quality: Optional[Dict[str, Any]] = (
            catalog_semantic_coverage(conn, library_id) if catalog else None
        )

        def _order(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            """组内排序：默认按分数；日期模式按日期（可用日期 > mtime > 无日期，同层再按分数）。"""
            if not sort_by:
                return sorted(entries, key=lambda x: (-x["score"], -x["hits"]))

            def key(x: Dict[str, Any]) -> Tuple[Any, ...]:
                value, source = _usable_doc_date(catalog.get(x["doc_id"]))
                cat = catalog.get(x["doc_id"]) or {}
                tier = 0 if value else (1 if cat.get("doc_date") else 2)
                if sort_by == "date_desc":
                    return (tier, -_date_ord(value or cat.get("doc_date") or ""), -x["score"], -x["hits"])
                return (tier, _date_ord(value or cat.get("doc_date") or ""), -x["score"], -x["hits"])

            return sorted(entries, key=key)

        # matter 优先分配：同一 matter 最多 per_matter 篇进 docs，避免大 matter 挤掉其它候选。
        # 先按分数取前 400 个候选再分组——候选可能上千（泛词命中），全量分组会让 matter 数失真。
        ranked = _order(list(candidates.values()))[:400]
        for entry in ranked:
            cat = catalog.get(entry["doc_id"]) or {}
            ident = _group_identity(cat.get("matter_id", ""), cat.get("folder", ""), entry["doc_id"])
            key = ident["group_id"]
            group = groups.setdefault(
                key, {"group_id": key, "group_kind": ident["group_kind"], "score": 0.0, "entries": []}
            )
            group["entries"].append(entry)
            group["score"] = max(group["score"], entry["score"])

        def _group_key(key: str) -> Tuple[Any, ...]:
            if not sort_by:
                return (-groups[key]["score"], key)
            best_entry = _order(groups[key]["entries"])[0]
            value, _source = _usable_doc_date(catalog.get(best_entry["doc_id"]))
            cat = catalog.get(best_entry["doc_id"]) or {}
            tier = 0 if value else (1 if cat.get("doc_date") else 2)
            value = value or cat.get("doc_date") or ""
            if sort_by == "date_desc":
                return (tier, -_date_ord(value), -groups[key]["score"], key)
            return (tier, _date_ord(value), -groups[key]["score"], key)

        ordered_groups = sorted(groups, key=_group_key)

        chosen: List[Dict[str, Any]] = []
        for key in ordered_groups:
            entries = _order(groups[key]["entries"])
            for entry in entries[:per_matter]:
                if len(chosen) >= limit:
                    break
                chosen.append(entry)
            if len(chosen) >= limit:
                break

        card_ids: List[str] = []
        for key in ordered_groups[:_MATTER_CARDS]:
            for entry in _order(groups[key]["entries"])[:per_matter]:
                card_ids.append(entry["doc_id"])
        title_map = _title_map(conn, card_ids) if card_ids else {}

        for entry in chosen:
            cat = catalog.get(entry["doc_id"]) or {}
            ident = _group_identity(cat.get("matter_id", ""), cat.get("folder", ""), entry["doc_id"])
            doc_row = {
                "doc_id": entry["doc_id"],
                "title": cat.get("display_title") or title_map.get(entry["doc_id"]) or entry["doc_id"],
                "group_id": ident["group_id"],
                "group_kind": ident["group_kind"],
                "matter_id": cat.get("matter_id") or "",
                "folder": cat.get("folder") or "",
                "hits": entry["hits"],
                "title_hit": bool(entry.get("title_hit")),
                "snippet": _snippet(entry.get("best_text") or ""),
                "page": _page_of_chunk(conn, entry.get("best_chunk") or "") + 1,
            }
            if date_mode:
                doc_row["doc_date"] = cat.get("doc_date") or ""
                doc_row["date_source"] = cat.get("date_source") or "none"
                doc_row["date_confidence"] = cat.get("date_confidence") or "none"
            docs.append(doc_row)

        for key in ordered_groups[:_MATTER_CARDS]:
            entries = _order(groups[key]["entries"])
            if catalog_docs:
                # 目录谓词命中优先：问「某客户最新一份信贷协议」时，组内 best 必须是命中的那份，
                # 而不是同组里分数更高的别的文书（2026-10-20 题 013 实踩）。
                matched_entries = [e for e in entries if e["doc_id"] in catalog_docs]
                if matched_entries:
                    entries = matched_entries + [e for e in entries if e["doc_id"] not in catalog_docs]
            best = entries[0]
            best_cat = catalog.get(best["doc_id"]) or {}
            matched_docs = [
                catalog_docs[e["doc_id"]] for e in entries if e["doc_id"] in catalog_docs
            ]
            kind = groups[key]["group_kind"]
            card = {
                "group_id": key,
                "group_kind": kind,
                "n_docs": len(entries),
                "folder": best_cat.get("folder") or "",
                "best": {
                    "doc_id": best["doc_id"],
                    "title": best_cat.get("display_title") or title_map.get(best["doc_id"]) or best["doc_id"],
                    "snippet": _snippet(best.get("best_text") or "", 160),
                },
                "docs": [
                    {
                        "doc_id": entry["doc_id"],
                        "title": (catalog.get(entry["doc_id"]) or {}).get("display_title")
                        or title_map.get(entry["doc_id"])
                        or entry["doc_id"],
                    }
                    for entry in entries[:per_matter]
                ],
            }
            if date_mode:
                card["doc_date"] = best_cat.get("doc_date") or ""
                card["date_source"] = best_cat.get("date_source") or "none"
                card["date_confidence"] = best_cat.get("date_confidence") or "none"
                card["best"]["doc_date"] = best_cat.get("doc_date") or ""
                card["best"]["date_source"] = best_cat.get("date_source") or "none"
                card["best"]["date_confidence"] = best_cat.get("date_confidence") or "none"
            if kind == "case":
                card["matter_id"] = key
            if matched_docs:
                card["catalog_hit"] = True
                card["matched_docs"] = matched_docs[:5]
            matter_list.append(card)
    finally:
        conn.close()

    # 有 catalog 时 docs 与 matters 内容重复（都带 doc_id/title），只保留紧凑的 matters 视图，
    # 避免单次工具结果膨胀（2026-10-18 实踩：双份清单把上下文顶到 155k tokens 触发 400）。
    # 注意：不要留空 docs 数组——模型会把 "docs": [] 读成「没找到」，随后退化成回显题面。
    kind_counts: Dict[str, int] = {}
    for g in groups.values():
        kind_counts[g["group_kind"]] = kind_counts.get(g["group_kind"], 0) + 1
    result: Dict[str, Any] = {
        "query": query,
        "library_id": library_id,
        "total_docs": len(candidates),
        "total_groups": len(groups),
        "group_kinds": kind_counts,
        "total_matters": kind_counts.get("case", 0),
        "returned_matters": len(matter_list),
        "returned_docs": len(docs),
        "matters": matter_list,
        "catalog": bool(catalog),
        "note": (
            "matters 为按 group 归并的枚举视图（group_kind=case/folder/doc；"
            "best.snippet 是最佳证据片段，docs 列出该组命中文档）。"
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
    if entity_name:
        result["entity"] = {
            "entity_contains": entity_name,
            "matched_docs": len(entity_rows),
            "matched_groups": len(entity_groups),
            "scoped_docs": len(candidates),
        }
        result["note"] = result["note"] + (
            " 实体模式：候选已收窄到提到该实体的分组内；配合 filename_contains 与 "
            "sort_by=date_desc 可一次拿到「某客户最新一份某类文档」。"
        )
        # 实体 + 文件类型 + 日期排序后只剩一组：这是确定性最高的定位结果，
        # 明确标成 authoritative，避免模型改答同客户其它文书（2026-10-20 题 013 实踩：
        # 模型拿到唯一信贷协议卡片，却改答 SAFE）。
        if filename_contains and sort_by and len(matter_list) == 1 and candidates:
            only = matter_list[0]
            best = only.get("best") or {}
            result["authoritative"] = {
                "doc_id": best.get("doc_id"),
                "title": best.get("title"),
                "doc_date": only.get("doc_date") or "",
                "date_source": only.get("date_source") or "none",
                "snippet": best.get("snippet") or "",
                "instruction": (
                    "实体+文件类型筛选后只命中这一组：本题答案必须基于该文档作答"
                    "（先用 doc_read 读正文确认条款），不要用同客户的其它文书替代。"
                ),
            }
    if date_mode:
        dated = 0
        mtime_only = 0
        for entry in candidates.values():
            value, _source = _usable_doc_date(catalog.get(entry["doc_id"]))
            if value:
                dated += 1
            elif (catalog.get(entry["doc_id"]) or {}).get("doc_date"):
                mtime_only += 1
        result["date_sort"] = {
            "sort_by": sort_by or "",
            "date_after": after or "",
            "date_before": before or "",
            "dated_docs": dated,
            "mtime_only_docs": mtime_only,
            "invalid": invalid,
            "warning": date_warning,
        }
        result["note"] = result["note"] + (
            " 日期模式：doc_date 为目录里的文档日期（YYYY-MM-DD，date_source=text/filename/mtime，"
            "date_confidence=high/medium/low）。排序按「正文/文件名日期 > 仅 mtime > 无日期」，同层按日期；"
            "mtime 只是文件落盘时间（拷贝/迁移会变），**不参与 date_after/date_before 过滤**。"
            "涉及「最新」结论时用 doc_read 读正文核对落款。"
        )
    if catalog:
        result["catalog_quality"] = quality
    if not catalog:
        result["docs"] = docs
    return result


_READ_STOPWORDS = {
    "most", "more", "the", "and", "for", "with", "that", "this", "from", "have", "has",
    "are", "was", "were", "will", "shall", "such", "other", "than", "into", "upon", "may",
    "not", "any", "all", "its", "their", "there", "been", "being", "about", "over",
}


def _query_terms(query: str) -> List[str]:
    """读页检索词：去疑问/虚词，避免 "most" 这类词把匹配带到无关段落。"""
    return [t for t in _tokens(query)[:10] if t.lower() not in _READ_STOPWORDS][:6]


def _section_rows(
    conn: sqlite3.Connection, doc_id: str, section: str, limit: int = 8
) -> List[sqlite3.Row]:
    """按章节号定位：找到 "Section X" / "§ X" 标题所在块，从那里往后取若干块。

    2026-10-20 题 013 实踩：读页只按关键词匹配，模型读到了文档却翻不到 Section 2.15，
    最终答「信贷协议没有 MFN 条款」。章节是比关键词更确定的定位方式。
    """
    name = str(section or "").strip().lstrip("§").strip()
    if not name:
        return []
    try:
        rows = conn.execute(
            "select text_clean, page_start, chunk_id from canonical_chunks "
            "where doc_id=? order by page_start, chunk_id limit 600",
            (doc_id,),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    low = name.lower()
    for needle in (f"section {low}", f"§ {low}", f"{low}."):
        for idx, row in enumerate(rows):
            if needle in str(row["text_clean"] or "").lower():
                return rows[idx : idx + limit]
    for idx, row in enumerate(rows):
        if low in str(row["text_clean"] or "").lower():
            return rows[idx : idx + limit]
    return []


def read_documents(
    *,
    library_id: str = "default",
    doc_ids: List[str],
    query: str = "",
    max_chars_per_doc: int = 1200,
    mode: str = "head",
    section: str = "",
) -> Dict[str, Any]:
    """批量读页：head=从头按页读；match=读与 query 相关的段落（无命中回落 head）；
    section=按章节号（如 "2.15"）定位并从该章节往后读。"""
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
            from_section = False
            if section:
                rows = _section_rows(conn, doc_id, section)
                from_section = bool(rows)
            if not rows and mode == "match" and query:
                terms = _query_terms(query)
                if terms:
                    # 先按 AND（精确）；无命中退到 OR——术语写法不一（"MFN" vs "Most Favored Nation"）
                    # 时全词 AND 会直接落空，模型据此判「文档里没有」，2026-10-20 题 013 实踩。
                    like_and = " and ".join("text_clean like ?" for _ in terms)
                    rows = conn.execute(
                        f"select text_clean, page_start, chunk_id from canonical_chunks "
                        f"where doc_id=? and {like_and} order by page_start, chunk_id limit 6",
                        (doc_id, *[f"%{t}%" for t in terms]),
                    ).fetchall()
                    if not rows:
                        # 退化路径要按「命中词数」排序：单纯 OR 会让 "Most Favored"
                        # 命中 only "most recent …" 的无关段落（2026-10-20 题 013 实踩）。
                        like_or = " or ".join("text_clean like ?" for _ in terms)
                        candidates = conn.execute(
                            f"select text_clean, page_start, chunk_id from canonical_chunks "
                            f"where doc_id=? and ({like_or}) limit 60",
                            (doc_id, *[f"%{t}%" for t in terms]),
                        ).fetchall()
                        scored = []
                        for row in candidates:
                            hay = str(row["text_clean"] or "").lower()
                            hits = sum(1 for t in terms if t.lower() in hay)
                            scored.append((-hits, int(row["page_start"] or 0), row["chunk_id"], row))
                        scored.sort(key=lambda item: item[:3])
                        rows = [item[3] for item in scored[:6]]
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
            doc_row = {
                "doc_id": doc_id,
                "title": cat.get("display_title") or doc_meta["title"],
                "matter_id": cat.get("matter_id") or "",
                "page_count": int(doc_meta["page_count"] or 0),
                "chars": used,
                "total_chars": total,
                "truncated": total > used,
                "text": "\n".join(parts),
            }
            if section:
                doc_row["section"] = section
                doc_row["section_found"] = from_section
            out.append(doc_row)
    finally:
        conn.close()
    note = "text 中 [pN] 为页码；truncated=true 表示只读了开头部分。"
    if section:
        note += " section 模式从该章节标题所在块开始读；section_found=false 表示没找到该章节，已回退到普通读页。"
    return {"docs": out, "mode": "section" if section else mode, "note": note}
