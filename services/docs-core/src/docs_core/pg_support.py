"""PostgreSQL 存储后端支撑层（KB_STACK=pg 档位）。

迁移方案见 DredgeAI ``docs/knowledge-pg-pgvector-migration-plan-20261028.md``（v4）。
结构：``KB_STACK`` 档位键决定整套存储实现（legacy=SQLite+Qdrant｜pg=PostgreSQL+pgvector），
一个键原子切换，禁止半迁移。

关系层复用既有 SQL 面的方式是 **协议适配** 而非逐方法重写：``PgConnection`` 提供
sqlite3.Connection 的连接协议，把 SQLite 方言在执行前显式翻译为 PG 方言——
翻译规则全部集中在 :func:`translate_sql`，逐条可测：

1. ``?`` 占位符 → ``%s``（引号内不动；引号外裸 ``%`` 转义为 ``%%``）
2. ``INSERT OR REPLACE INTO t`` → ``ON CONFLICT (主键) DO UPDATE SET``（主键查 information_schema）
3. ``INSERT OR IGNORE INTO`` → ``ON CONFLICT DO NOTHING``
4. ``LIKE`` → ``ILIKE``（SQLite LIKE 不区分大小写）
5. ``INTEGER PRIMARY KEY AUTOINCREMENT`` → ``BIGSERIAL PRIMARY KEY``（DDL 兜底改写）
6. ``PRAGMA table_info(t)`` → information_schema 列清单（模拟 6 列形状）；其余 PRAGMA 返回空
7. ``SELECT last_insert_rowid()`` → 返回最近一次 ``RETURNING`` 缓存值（serial 主键 INSERT 自动加 RETURNING）
8. FTS5 专用语句（``bm25(...)``/``MATCH``）：仅识别 doc_search.py 的固定查询模板并翻译为
   tsvector 查询，其余 FTS5 语句一律抛错——canonical 的 FTS 面（建表/重建/search）由
   ``PgCanonicalSQLiteStore`` 显式覆写，不走本翻译。

行协议：``PgRow`` 模拟 sqlite3.Row（``row["col"]``/``row[0]``/``dict(row)``/元组解包）。
异常：psycopg 的 duplicate 类错误转 ``sqlite3.OperationalError``（既有代码
``except sqlite3.OperationalError: pass`` 的幂等加列模式依赖它），唯一冲突转
``sqlite3.IntegrityError``。

组文件：PG 档位下 meta/index/canonical 全部共库（表自带 library_id/doc_id 列），
"组文件"路由经 ``library_registry.resolve_index_db_path`` 的 pg 分支归一到默认路径，
docs_service 的组缓存自然收敛为单实例。

向量层见 ``step06_vectors/pg_vector_store.py``（collection_name 列复刻 Qdrant 组隔离，
``score = 1 - <=>`` 距离）。

env 键：
- ``KB_STACK``：``legacy``（默认）| ``pg``
- ``KNOWLEDGE_PG_DSN``：连接串，支持 ``postgresql://`` URL、``key=value``、Npgsql 风格
  ``Host=..;Port=..;Database=..;Uid=..;Pwd=..``（Database 指知识库，如 dredge_knowledge，
  缺库首连自动建）
- ``KNOWLEDGE_PG_VECTOR_DIM``：向量列维度（默认 1024）
- ``ANGINEER_PG_CONNECT_TIMEOUT``：连接超时秒（默认 10）
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import threading
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

KB_STACK_ENV = "KB_STACK"
PG_DSN_ENV = "KNOWLEDGE_PG_DSN"
# 知识库表所在 schema（2026-10-29 起并入业务同一 database，用独立 schema 隔离，
# EF 迁移只碰 dredge_business/dredge_base，互不越界）
KNOWLEDGE_PG_SCHEMA_ENV = "KNOWLEDGE_PG_SCHEMA"
DEFAULT_PG_SCHEMA = "dredge_knowledge"


def pg_schema() -> str:
    return (os.getenv(KNOWLEDGE_PG_SCHEMA_ENV) or DEFAULT_PG_SCHEMA).strip() or DEFAULT_PG_SCHEMA
PG_VECTOR_DIM_ENV = "KNOWLEDGE_PG_VECTOR_DIM"
DEFAULT_VECTOR_DIM = 1024
STACK_LEGACY = "legacy"
STACK_PG = "pg"

# PG 档位的「库路径」哨兵：run_with_write_lock 等以 Path 为锁 key / 日志字段的调用方
# 仍需要拿到一个 Path；它不参与任何磁盘 IO（Path.resolve 只做字符串规范化）。
from pathlib import Path as _Path

PG_SENTINEL_DB_PATH = _Path("//__pg_dredge_knowledge__")

# serial 主键表（适配器对 INSERT 自动附加 RETURNING 以支撑 last_insert_rowid）
_AUTOINCREMENT_TABLES: Dict[str, str] = {
    "parse_records": "id",
    "parse_task_steps": "id",
    "parse_stage_steps": "id",
    "doc_blocks": "id",
}


def kb_stack() -> str:
    """读档位键；非法值 fail-fast（半迁移状态的唯一入口在这里被挡）。"""
    value = (os.getenv(KB_STACK_ENV) or "").strip().lower()
    if not value:
        return STACK_LEGACY
    if value not in (STACK_LEGACY, STACK_PG):
        raise ValueError(f"非法 {KB_STACK_ENV}={value!r}（合法值 legacy/pg）")
    return value


def is_pg() -> bool:
    return kb_stack() == STACK_PG


def vector_dimension() -> int:
    raw = (os.getenv(PG_VECTOR_DIM_ENV) or "").strip()
    try:
        dim = int(raw) if raw else DEFAULT_VECTOR_DIM
    except ValueError:
        dim = DEFAULT_VECTOR_DIM
    return dim if dim > 0 else DEFAULT_VECTOR_DIM


HNSW_INDEX_NAME = "idx_vector_records_hnsw"


def drop_vector_hnsw_index(conn: "PgConnection") -> bool:
    """摘掉 HNSW 索引（批量导入前）：逐行维护 HNSW 的成本会把远程实例打到
    连接超时（2026-10-29 实测）；导完由 recreate_vector_hnsw_index 一次重建。
    返回 True=已确保摘除（调用方据此决定是否重建；DDL 的 rowcount 恒 -1 不可用）。"""
    try:
        conn.execute("DROP INDEX IF EXISTS " + HNSW_INDEX_NAME)
        conn.commit()
        return True
    except Exception:  # noqa: BLE001
        conn.rollback()
        return False


def recreate_vector_hnsw_index(conn: "PgConnection") -> None:
    """重建 HNSW 索引（批量导入完成后调用；万级点数秒级）。"""
    dim = vector_dimension()
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS {HNSW_INDEX_NAME} "
        f"ON vector_records USING hnsw (embedding vector_cosine_ops)"
    )
    conn.commit()


def parse_pg_dsn(value: Optional[str] = None) -> Dict[str, Any]:
    """把三类 DSN 写法解析成 psycopg3 connect kwargs。"""
    raw = (value or os.getenv(PG_DSN_ENV) or "").strip()
    if not raw:
        raise RuntimeError(
            f"KB_STACK=pg 需要设置 {PG_DSN_ENV}（如 "
            "Host=test.bim-ace.com;Port=10111;Database=dredge_knowledge;Uid=postgres;Pwd=***）"
        )
    search_path_option = f"-c search_path={pg_schema()},public"
    if raw.startswith("postgres://") or raw.startswith("postgresql://"):
        return {"conninfo": raw, "options": search_path_option}
    if "=" in raw and ";" not in raw:
        return {"conninfo": raw, "options": search_path_option}
    # Npgsql / 分号键值风格（与业务后端 appsettings 同写法，直接复用连接串）
    alias = {
        "host": "host", "server": "host", "data source": "host",
        "port": "port",
        "database": "dbname", "db": "dbname",
        "user": "user", "uid": "user", "user id": "user", "username": "user",
        "password": "password", "pwd": "password",
    }
    kwargs: Dict[str, Any] = {}
    for part in raw.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        key, _, val = part.partition("=")
        norm = alias.get(key.strip().lower())
        if norm and val.strip():
            kwargs[norm] = val.strip()
    if "host" not in kwargs or "dbname" not in kwargs:
        raise RuntimeError(f"{PG_DSN_ENV} 解析失败（缺 host/database）: {raw[:64]}…")
    kwargs["options"] = f"-c search_path={pg_schema()},public"
    timeout = (os.getenv("ANGINEER_PG_CONNECT_TIMEOUT") or "30").strip()
    try:
        kwargs["connect_timeout"] = max(1, int(timeout))
    except ValueError:
        kwargs["connect_timeout"] = 30
    return kwargs


# ---------------------------------------------------------------------------
# 行 / 游标协议
# ---------------------------------------------------------------------------


class PgRow(tuple):
    """模拟 sqlite3.Row：按列名/索引取值、dict(row)、元组解包。

    继承 tuple 让 ``row[0]`` 与解包走原生路径；带 ``keys()`` 后 ``dict(row)`` 走
    mapping 路径（CPython dict() 优先查 keys 属性）。tuple 子类不支持 __slots__，
    列名映射挂实例属性（每行一个小 dict，量级可接受）。
    """

    def __new__(cls, columns: Sequence[str], values: Tuple[Any, ...]):
        obj = super().__new__(cls, values)
        obj._columns = tuple(columns)
        obj._map = {name: idx for idx, name in enumerate(columns)}
        return obj

    def keys(self) -> List[str]:
        return list(self._columns)

    def __getitem__(self, key):  # type: ignore[override]
        if isinstance(key, str):
            idx = self._map.get(key)
            if idx is None:
                raise IndexError(f"no such column: {key}")
            return super().__getitem__(idx)
        return super().__getitem__(key)

    def __contains__(self, key: object) -> bool:
        if isinstance(key, str):
            return key in self._map
        return super().__contains__(key)

    def get(self, key: str, default: Any = None) -> Any:
        idx = self._map.get(key)
        return super().__getitem__(idx) if idx is not None else default


class PgCursor:
    """包装 psycopg cursor，fetch 结果包装成 PgRow。"""

    def __init__(self, cursor: Any) -> None:
        self._cursor = cursor
        self._columns: List[str] = []

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount or 0

    @property
    def lastrowid(self) -> Optional[int]:
        return getattr(self, "_lastrowid", None)

    @property
    def description(self):
        return self._cursor.description

    def _wrap(self, rows: Sequence[Sequence[Any]]) -> List[PgRow]:
        if not self._columns:
            self._columns = [d.name for d in (self._cursor.description or [])]
        return [PgRow(self._columns, tuple(row)) for row in rows]

    def fetchone(self) -> Optional[PgRow]:
        row = self._cursor.fetchone()
        if row is None:
            return None
        return self._wrap([row])[0]

    def fetchall(self) -> List[PgRow]:
        rows = self._cursor.fetchall()
        if not rows:
            return []
        return self._wrap(rows)

    def fetchmany(self, size: int = 1) -> List[PgRow]:
        rows = self._cursor.fetchmany(size)
        if not rows:
            return []
        return self._wrap(rows)

    def close(self) -> None:
        try:
            self._cursor.close()
        except Exception:  # noqa: BLE001
            pass

    def __iter__(self) -> Iterator[PgRow]:
        for row in self._cursor.__iter__():
            yield self._wrap([row])[0]

    def __enter__(self) -> "PgCursor":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


# ---------------------------------------------------------------------------
# SQL 方言翻译
# ---------------------------------------------------------------------------

_AUTOINCREMENT_RE = re.compile(
    r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b", re.IGNORECASE)
_INSERT_OR_REPLACE_RE = re.compile(
    r"\bINSERT\s+OR\s+REPLACE\s+INTO\s+([\"'\w\.]+)", re.IGNORECASE)
_INSERT_OR_IGNORE_RE = re.compile(
    r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", re.IGNORECASE)
_FTS_STATEMENT_RE = re.compile(r"\bbm25\s*\(\s*canonical_chunk_fts\s*\)", re.IGNORECASE)
_FTS_MATCH_RE = re.compile(r"canonical_chunk_fts\s+match\s+\?", re.IGNORECASE)
_LAST_ROWID_RE = re.compile(r"^\s*select\s+last_insert_rowid\s*\(\s*\)\s*$", re.IGNORECASE)
_PRAGMA_INFO_RE = re.compile(r"^\s*pragma\s+table_info\s*\(\s*\"?([\w\.]+)\"?\s*\)\s*$", re.IGNORECASE)
_PRAGMA_ANY_RE = re.compile(r"^\s*pragma\b", re.IGNORECASE)
_INSERT_COLUMNS_RE = re.compile(r"\(([^()]*)\)\s*VALUES", re.IGNORECASE | re.DOTALL)


def _sub_outside_quotes(pattern: re.Pattern, repl, sql: str) -> str:
    """只在引号外做正则替换（引号内是字符串字面量，不是 SQL 语法）。"""
    n = len(sql)
    segments: List[Tuple[int, int, bool]] = []  # (start, end, is_plain)
    in_str = False
    seg_start = 0
    i = 0
    while i < n:
        ch = sql[i]
        if in_str:
            if ch == "'":
                if i + 1 < n and sql[i + 1] == "'":
                    i += 2
                    continue
                in_str = False
                segments.append((seg_start, i + 1, False))
                seg_start = i + 1
        elif ch == "'":
            if seg_start < i:
                segments.append((seg_start, i, True))
            in_str = True
            seg_start = i
        i += 1
    if seg_start < n:
        segments.append((seg_start, n, not in_str))
    out: List[str] = []
    for start, end, plain in segments:
        chunk = sql[start:end]
        out.append(chunk if not plain else pattern.sub(repl, chunk))
    return "".join(out)


def _fts5_match_to_tsquery(match_expr: str) -> str:
    """FTS5 MATCH 串（``\"tok1\" OR \"tok2\"``）→ tsquery 串（``tok1 | tok2``）。

    doc_search 的 match 计划由 ``"token" OR ...`` 构成（见 canonical_sql_store
    ``_build_fts_match_query``）；token 保留到引号边界，无法解析时按原文清洗。
    """
    tokens = re.findall(r'"([^"]*)"', match_expr)
    if not tokens:
        tokens = [t for t in re.split(r"\s+OR\s+", match_expr, flags=re.IGNORECASE) if t]
    cleaned = []
    for token in tokens:
        token = re.sub(r"[^\w\u4e00-\u9fff]+", "", token)
        if token:
            cleaned.append(token)
    if not cleaned:
        return ""
    return " | ".join(cleaned)


def translate_sql(
    sql: str,
    params: Optional[Sequence[Any]],
    table_pk_resolver,
) -> Tuple[str, Optional[Sequence[Any]], Dict[str, Any]]:
    """SQLite 方言 → PG 方言。返回 (sql, params, notes)。

    ``table_pk_resolver(table) -> List[str]``：主键列清单（带缓存，由 PgConnection 提供）。
    """
    notes: Dict[str, Any] = {}

    stripped = sql.strip()
    # PRAGMA：table_info 模拟成 information_schema 查询；其余吞掉（执行层处理）
    pragma_info = _PRAGMA_INFO_RE.match(stripped)
    if pragma_info:
        table = pragma_info.group(1).strip('"')
        pg = (
            "SELECT ordinal_position - 1 AS cid, column_name AS name, data_type AS type, "
            "CASE WHEN is_nullable = 'NO' THEN 1 ELSE 0 END AS notnull, "
            "NULL AS dflt_value, 0 AS pk "
            "FROM information_schema.columns WHERE table_name = ? "
            "AND table_schema = ANY(current_schemas(false)) ORDER BY ordinal_position"
        )
        notes["pragma_info"] = table
        return _sub_outside_quotes(re.compile(r"\?"), "%s", pg), params, notes
    if _PRAGMA_ANY_RE.match(stripped):
        notes["pragma_noop"] = True
        return sql, params, notes
    if _LAST_ROWID_RE.match(stripped):
        notes["last_rowid"] = True
        return sql, params, notes

    # FTS5 查询模板（doc_search._text_hits）：bm25(...) → -ts_rank，match ? → fts @@ to_tsquery
    if _FTS_STATEMENT_RE.search(stripped) and _FTS_MATCH_RE.search(stripped):
        pg_sql = _sub_outside_quotes(
            _FTS_STATEMENT_RE, "-ts_rank(canonical_chunk_fts.fts, q.tsq) AS score", stripped)
        pg_sql = _sub_outside_quotes(
            _FTS_MATCH_RE, "canonical_chunk_fts.fts @@ q.tsq", pg_sql)
        pg_sql = re.sub(
            r"from\s+canonical_chunk_fts",
            "from canonical_chunk_fts, to_tsquery('simple', ?) AS q(tsq)",
            pg_sql,
            flags=re.IGNORECASE,
        )
        new_params: List[Any] = []
        params_list = list(params or [])
        tsq_placeholder_at: List[int] = []
        # 参数顺序：match ? 在前，library_id/limit 在后——翻译后 to_tsquery 参数顶替 match 位
        match_param_idx = None
        # 找出 params 里对应 match 的那个位置：SQL 中 match ? 是第 1 个占位符
        for idx, p in enumerate(params_list):
            if isinstance(p, str) and ("OR" in p or '"' in p):
                match_param_idx = idx
                break
        if match_param_idx is None:
            match_param_idx = 0
        for idx, p in enumerate(params_list):
            if idx == match_param_idx:
                tsq = _fts5_match_to_tsquery(str(p))
                if not tsq:
                    notes["fts_empty"] = True
                    return "SELECT NULL WHERE FALSE", [], notes
                new_params.append(tsq)
            else:
                new_params.append(p)
        pg_sql = _sub_outside_quotes(re.compile(r"\?"), "%s", pg_sql)
        notes["fts5_translated"] = True
        return pg_sql, new_params, notes

    if _FTS_STATEMENT_RE.search(stripped) or _FTS_MATCH_RE.search(stripped):
        raise NotImplementedError(
            "PG 档位不支持未经翻译的 FTS5 语句（canonical FTS 面请覆写实现）: "
            + stripped[:120])

    out = sql
    # DDL：AUTOINCREMENT → BIGSERIAL
    if _AUTOINCREMENT_RE.search(out):
        out = _AUTOINCREMENT_RE.sub("BIGSERIAL PRIMARY KEY", out)
        notes["autoincrement"] = True

    # INSERT OR REPLACE → ON CONFLICT (pk) DO UPDATE
    m = _INSERT_OR_REPLACE_RE.search(out)
    if m:
        table = m.group(1).strip('"').split(".")[-1]
        cols_match = _INSERT_COLUMNS_RE.search(out)
        if not cols_match:
            raise NotImplementedError(
                f"PG 档位 INSERT OR REPLACE 需要显式列清单: {table}")
        columns = [c.strip().strip('"') for c in cols_match.group(1).split(",") if c.strip()]
        pks = table_pk_resolver(table)
        if not pks:
            raise RuntimeError(f"PG 档位 INSERT OR REPLACE 找不到表主键: {table}")
        set_clause = ", ".join(f"{c} = excluded.{c}" for c in columns if c not in pks)
        conflict = ", ".join(pks)
        out = _INSERT_OR_REPLACE_RE.sub(f"INSERT INTO {m.group(1)}", out)
        out = out.rstrip().rstrip(";") + (
            f" ON CONFLICT ({conflict}) DO UPDATE SET {set_clause}")
        notes["insert_or_replace"] = table

    # INSERT OR IGNORE → ON CONFLICT DO NOTHING
    if _INSERT_OR_IGNORE_RE.search(out):
        out = _INSERT_OR_IGNORE_RE.sub("INSERT INTO", out)
        out = out.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
        notes["insert_or_ignore"] = True

    # LIKE → ILIKE（SQLite LIKE 不区分大小写）
    out = _sub_outside_quotes(re.compile(r"\bLIKE\b", re.IGNORECASE), "ILIKE", out)

    # ? → %s；随后把引号外残余裸 % 转义（psycopg 参数化模式）
    out = _sub_outside_quotes(re.compile(r"\?"), "%s", out)
    if params is not None:
        out = re.sub(r"%(?!s)", "%%", out)
    return out, params, notes


# ---------------------------------------------------------------------------
# 连接
# ---------------------------------------------------------------------------


class PgConnection:
    """sqlite3.Connection 协议的 psycopg3 适配器（连接不跨线程复用，随用随建）。"""

    def __init__(self, dsn_kwargs: Dict[str, Any]) -> None:
        import psycopg

        self._dsn_kwargs = dsn_kwargs
        self._conn = psycopg.connect(**dsn_kwargs)
        self._row_factory: Any = None  # 兼容 conn.row_factory = sqlite3.Row 赋值
        self._pk_cache: Dict[str, List[str]] = {}
        self._last_returning_id: Optional[int] = None
        self._total_changes = 0
        # 会话级禁并行：小盘实例 /dev/shm 不足时，并行 worker 的动态共享内存
        # 分配直接报 DiskFull（2026-10-29 test.bim-ace.com 实测，64MB 都分不出）；
        # 本工作负载（点查/批量写/HNSW）无并行收益，会话内关掉零成本规避
        try:
            cur = self._conn.cursor()
            cur.execute("SET max_parallel_workers_per_gather = 0")
            cur.execute("SET max_parallel_maintenance_workers = 0")
            cur.close()
        except Exception:  # noqa: BLE001 - 老版本无此参数时忽略
            pass

    # -- sqlite3 兼容面 ----------------------------------------------------

    row_factory = property(lambda self: self._row_factory,
                           lambda self, v: setattr(self, "_row_factory", v))

    @property
    def total_changes(self) -> int:
        """本连接累计受影响行数（调用方只判 >0，逐次累加 rowcount 即可）。"""
        return self._total_changes

    def _resolve_pks(self, table: str) -> List[str]:
        if table in self._pk_cache:
            return self._pk_cache[table]
        cur = self._conn.execute(
            """
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            WHERE tc.table_name = %s AND tc.constraint_type = 'PRIMARY KEY'
              AND tc.table_schema = ANY(current_schemas(false))
            ORDER BY kcu.ordinal_position
            """,
            (table,),
        )
        pks = [r[0] for r in cur.fetchall()]
        cur.close()
        self._pk_cache[table] = pks
        return pks

    def _wrap_error(self, exc: Exception) -> Exception:
        sqlstate = getattr(exc, "sqlstate", None)
        if sqlstate == "23505":  # unique_violation
            return sqlite3.IntegrityError(str(exc))
        if sqlstate in ("42710", "42701", "42P07", "42723"):
            # duplicate_object / duplicate_column / duplicate_table / duplicate_function
            return sqlite3.OperationalError(str(exc))
        return exc

    def _maybe_add_returning(self, sql: str) -> str:
        up = sql.strip().upper()
        if not up.startswith("INSERT"):
            return sql
        m = re.match(r"INSERT\s+INTO\s+([\"'\w\.]+)", sql, re.IGNORECASE)
        if not m:
            return sql
        table = m.group(1).strip('"').split(".")[-1]
        pk = _AUTOINCREMENT_TABLES.get(table)
        if pk and "RETURNING" not in up:
            return sql.rstrip().rstrip(";") + f" RETURNING {pk}"
        return sql

    def execute(self, sql: str, params: Optional[Sequence[Any]] = None) -> PgCursor:
        translated, params2, notes = translate_sql(sql, params, self._resolve_pks)
        if notes.get("pragma_noop"):
            return _EmptyCursor()
        if notes.get("last_rowid"):
            return _ValueCursor([(self._last_returning_id,)])
        if notes.get("pragma_info"):
            cur = self._conn.execute(translated, (notes["pragma_info"],))
            return PgCursor(cur)
        run_sql = translated
        if notes.get("autoincrement") and run_sql.strip().upper().startswith("CREATE TABLE"):
            run_sql = run_sql.rstrip().rstrip(";")
        try:
            if params2 is None or (isinstance(params2, (list, tuple)) and len(params2) == 0):
                cursor = self._conn.execute(run_sql)
            else:
                cursor = self._conn.execute(run_sql, tuple(params2))
        except Exception as exc:  # noqa: BLE001
            raise self._wrap_error(exc) from exc
        wrapped = PgCursor(cursor)
        if cursor.rowcount and cursor.rowcount > 0:
            self._total_changes += int(cursor.rowcount)
        if " RETURNING " in run_sql.upper():
            try:
                row = cursor.fetchone()
                if row is not None:
                    self._last_returning_id = int(row[0])
            except Exception:  # noqa: BLE001
                pass
        return wrapped

    def executemany(self, sql: str, seq_of_params: Sequence[Sequence[Any]]) -> None:
        translated, _, notes = translate_sql(sql, None, self._resolve_pks)
        if notes.get("pragma_noop"):
            return
        if " RETURNING " in translated.upper():
            raise NotImplementedError("executemany 不支持 RETURNING")
        try:
            with self._conn.cursor() as cur:
                cur.executemany(
                    translated, [tuple(p) if p is not None else () for p in seq_of_params])
        except Exception as exc:  # noqa: BLE001
            raise self._wrap_error(exc) from exc

    def executescript(self, script: str) -> None:
        # 注册表 schema 等纯 DDL（无函数体/存储过程），按分号拆条执行
        for statement in re.split(r";\s*(?:\n|$)", script):
            statement = statement.strip()
            if statement:
                self.execute(statement)

    def cursor(self) -> PgCursor:
        raise NotImplementedError("PgConnection 不支持裸 cursor()，请用 execute()")

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:  # noqa: BLE001
            pass

    def __enter__(self) -> "PgConnection":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            self._conn.commit()
        else:
            self._conn.rollback()

    # -- 供导入器/导出器直用的底层句柄 ------------------------------------

    @property
    def raw(self) -> Any:
        return self._conn


class _EmptyCursor:
    def fetchone(self):
        return None

    def fetchall(self):
        return []

    def fetchmany(self, size: int = 1):
        return []

    rowcount = 0

    def close(self):
        pass

    def __iter__(self):
        return iter(())


class _ValueCursor:
    def __init__(self, rows: Sequence[Sequence[Any]]) -> None:
        self._rows = [tuple(r) for r in rows]

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def fetchmany(self, size: int = 1):
        return list(self._rows[:size])

    rowcount = 0

    def close(self):
        pass

    def __iter__(self):
        return iter(self._rows)


_CONNECT_LOCK = threading.Lock()
_READY_DONE = False
# thread-local 长连接：导入期每方法新建短连接会撞远程实例的连接建立抖动
# （2026-10-29 实测 ConnectionTimeout @ 7505 点第 3328 个），复用 + ping 失败重建
_THREAD_CONN = threading.local()


def _pg_connect_raw(dsn_kwargs: Dict[str, Any], dbname: Optional[str] = None) -> Any:
    import time

    import psycopg

    kwargs = dict(dsn_kwargs)
    if dbname is not None:
        kwargs["dbname"] = dbname
    last_exc: Optional[Exception] = None
    for attempt in range(3):
        try:
            return psycopg.connect(**kwargs)
        except Exception as exc:  # noqa: BLE001 - 远程实例网络抖动重试
            last_exc = exc
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
    assert last_exc is not None
    raise last_exc


def ensure_pg_ready(force: bool = False) -> None:
    """建库（如缺）+ 装扩展 + 建全部关系表（幂等；进程内只做一次）。

    程序自动行为，替代旧栈「打开 SQLite 文件即建表」的语义：
    1. 连 maintenance 库（默认 postgres）查 pg_database；
    2. 目标库不存在 → CREATE DATABASE（autocommit，PG 建库不能在事务内）；
    3. 目标库 CREATE EXTENSION IF NOT EXISTS vector/pg_trgm；
    4. 逐张执行全部 PG DDL。
    """
    global _READY_DONE
    if _READY_DONE and not force:
        return
    with _CONNECT_LOCK:
        if _READY_DONE and not force:
            return
        dsn_kwargs = parse_pg_dsn()
        dbname = dsn_kwargs.get("dbname")
        if not dbname and "conninfo" in dsn_kwargs:
            # URL / key=value conninfo 形式：用 psycopg 解析出 dbname
            import psycopg

            dbname = (psycopg.conninfo.conninfo_to_dict(dsn_kwargs["conninfo"])
                      .get("dbname"))
        if not dbname:
            raise RuntimeError(f"{PG_DSN_ENV} 缺 Database/dbname")
        # 1) 建库
        conn = _pg_connect_raw(dsn_kwargs, dbname="postgres")
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,))
                if cur.fetchone() is None:
                    logger.info("pg_support: 目标库 %s 不存在，自动创建", dbname)
                    cur.execute('CREATE DATABASE "{}"'.format(dbname.replace('"', '""')))
        finally:
            conn.close()
        # 2) 扩展 + 建表
        conn = _pg_connect_raw(dsn_kwargs)
        try:
            conn.autocommit = True
            with conn.cursor() as cur:
                # 建表含 CREATE INDEX：并行 build 要动态共享内存，小盘实例 DiskFull
                #（见 PgConnection.__init__ 同款规避；ensure 走原生连接需单独 SET）
                try:
                    cur.execute("SET max_parallel_workers_per_gather = 0")
                    cur.execute("SET max_parallel_maintenance_workers = 0")
                except Exception:  # noqa: BLE001
                    pass
                # 知识库独立 schema（同库并存业务 schema；扩展装入 public 全局共用）
                cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{pg_schema()}"')
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector SCHEMA public")
                cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm SCHEMA public")
                for ddl in iter_pg_ddl():
                    cur.execute(ddl)
            conn.commit()
        finally:
            conn.close()
        _READY_DONE = True
        logger.info("pg_support: PG 知识库就绪（db=%s, vector_dim=%d）",
                    dbname, vector_dimension())


def pg_connect(db_path: Optional[object] = None) -> PgConnection:
    """PG 档位统一连接入口（db_path 参数仅为兼容调用方签名，忽略）。

    thread-local 长连接复用：close() 后再取会自动重建；取回前 ping 失败也重建。
    事务语义不变（commit/rollback 仍由调用方控制）。
    """
    if not _READY_DONE:
        ensure_pg_ready()
    cached: Optional[PgConnection] = getattr(_THREAD_CONN, "conn", None)
    if cached is not None:
        try:
            cur = cached.raw.cursor()
            cur.execute("SELECT 1")
            cur.close()
            return cached
        except Exception:  # noqa: BLE001 - 连接已死，重建
            try:
                cached.close()
            except Exception:  # noqa: BLE001
                pass
            _THREAD_CONN.conn = None
    fresh = PgConnection(parse_pg_dsn())
    _THREAD_CONN.conn = fresh
    return fresh


# ---------------------------------------------------------------------------
# PG DDL（列名与类型语义与 SQLite 版逐列对齐；TEXT 时间戳保持字符串口径）
# ---------------------------------------------------------------------------


def iter_pg_ddl() -> Iterator[str]:
    dim = vector_dimension()
    yield """
    CREATE TABLE IF NOT EXISTS libraries (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """
    yield """
    CREATE TABLE IF NOT EXISTS nodes (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        type TEXT NOT NULL,
        visible INTEGER NOT NULL,
        library_id TEXT NOT NULL,
        file_path TEXT,
        status TEXT NOT NULL,
        parse_progress INTEGER NOT NULL DEFAULT 0,
        parse_stage TEXT,
        parse_error TEXT,
        parse_task_id TEXT,
        strategy TEXT NOT NULL DEFAULT 'doc_blocks_graph_v1',
        schema_version TEXT NOT NULL DEFAULT '1.0.0',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        deleted INTEGER NOT NULL DEFAULT 0
    )
    """
    yield "CREATE INDEX IF NOT EXISTS idx_nodes_library_type ON nodes (library_id, type, created_at)"
    yield """
    CREATE TABLE IF NOT EXISTS parse_tasks (
        id TEXT PRIMARY KEY,
        library_id TEXT NOT NULL,
        doc_id TEXT NOT NULL,
        status TEXT NOT NULL,
        progress INTEGER NOT NULL DEFAULT 0,
        stage TEXT NOT NULL,
        stage_message TEXT,
        error TEXT,
        schema_version TEXT NOT NULL DEFAULT '1.0.0',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """
    yield "CREATE INDEX IF NOT EXISTS idx_parse_tasks_doc_created ON parse_tasks (doc_id, created_at DESC)"
    yield """
    CREATE TABLE IF NOT EXISTS parse_task_steps (
        id BIGSERIAL PRIMARY KEY,
        task_id TEXT NOT NULL,
        doc_id TEXT NOT NULL,
        stage TEXT NOT NULL,
        progress INTEGER NOT NULL DEFAULT 0,
        stage_message TEXT,
        created_at TEXT NOT NULL
    )
    """
    yield "CREATE INDEX IF NOT EXISTS idx_parse_task_steps_task ON parse_task_steps (task_id, created_at ASC)"
    yield """
    CREATE TABLE IF NOT EXISTS parse_stage_steps (
        id BIGSERIAL PRIMARY KEY,
        doc_id TEXT NOT NULL,
        stage TEXT NOT NULL,
        step TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'done',
        detail TEXT DEFAULT '',
        created_at TEXT NOT NULL
    )
    """
    yield "CREATE INDEX IF NOT EXISTS idx_parse_stage_steps_doc_stage ON parse_stage_steps (doc_id, stage, created_at ASC)"
    yield """
    CREATE TABLE IF NOT EXISTS doc_parse_stages (
        doc_id TEXT NOT NULL,
        stage TEXT NOT NULL,
        status TEXT NOT NULL,
        message TEXT DEFAULT '',
        error TEXT DEFAULT '',
        started_at TEXT,
        finished_at TEXT,
        updated_at TEXT NOT NULL,
        input_summary TEXT DEFAULT '',
        output_summary TEXT DEFAULT '',
        fallback TEXT DEFAULT '',
        page_count INTEGER DEFAULT 0,
        is_scanned INTEGER DEFAULT 0,
        PRIMARY KEY (doc_id, stage)
    )
    """
    yield """
    CREATE TABLE IF NOT EXISTS tree_node (
        node_id TEXT PRIMARY KEY,
        tree_type TEXT NOT NULL,
        title TEXT NOT NULL DEFAULT '',
        parent_id TEXT,
        scope_id TEXT NOT NULL DEFAULT '',
        sort_order INTEGER NOT NULL DEFAULT 0,
        is_folder INTEGER NOT NULL DEFAULT 0,
        extra_json TEXT,
        created_at TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL DEFAULT '',
        deleted INTEGER NOT NULL DEFAULT 0
    )
    """
    yield ("CREATE INDEX IF NOT EXISTS idx_tree_node_scope "
           "ON tree_node(tree_type, scope_id, parent_id, sort_order)")
    # ---- index 库（doc_blocks / segments / corrections）----
    yield """
    CREATE TABLE IF NOT EXISTS doc_blocks (
        id BIGSERIAL PRIMARY KEY,
        doc_id TEXT NOT NULL,
        doc_name TEXT,
        page_idx INTEGER NOT NULL,
        page_width DOUBLE PRECISION NOT NULL,
        page_height DOUBLE PRECISION NOT NULL,
        block_seq INTEGER NOT NULL,
        block_uid TEXT NOT NULL,
        block_type TEXT NOT NULL,
        content_json TEXT NOT NULL,
        plain_text TEXT,
        bbox_abs_x1 DOUBLE PRECISION NOT NULL,
        bbox_abs_y1 DOUBLE PRECISION NOT NULL,
        bbox_abs_x2 DOUBLE PRECISION NOT NULL,
        bbox_abs_y2 DOUBLE PRECISION NOT NULL,
        page_seq INTEGER,
        sub_type TEXT,
        bbox_norm_x1 DOUBLE PRECISION,
        bbox_norm_y1 DOUBLE PRECISION,
        bbox_norm_x2 DOUBLE PRECISION,
        bbox_norm_y2 DOUBLE PRECISION,
        bbox_source TEXT,
        raw_title_level INTEGER,
        derived_title_level INTEGER,
        title_path TEXT,
        parent_block_uid TEXT,
        prev_block_uid TEXT,
        next_block_uid TEXT,
        explain_for_block_uid TEXT,
        explain_type TEXT,
        table_type TEXT,
        table_nest_level INTEGER,
        table_html TEXT,
        math_type TEXT,
        math_content TEXT,
        image_path TEXT,
        quality_score DOUBLE PRECISION,
        derived_confidence DOUBLE PRECISION,
        derived_by TEXT,
        derive_version TEXT,
        parser_version TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        is_active INTEGER NOT NULL
    )
    """
    yield "CREATE UNIQUE INDEX IF NOT EXISTS uq_doc_blocks_block_uid ON doc_blocks(block_uid)"
    yield "CREATE INDEX IF NOT EXISTS idx_doc_blocks_doc_page_seq ON doc_blocks(doc_id, page_idx, block_seq)"
    yield "CREATE INDEX IF NOT EXISTS idx_doc_blocks_doc_type ON doc_blocks(doc_id, block_type)"
    yield "CREATE INDEX IF NOT EXISTS idx_doc_blocks_doc_active ON doc_blocks(doc_id, is_active)"
    yield "CREATE INDEX IF NOT EXISTS idx_doc_blocks_doc_parent ON doc_blocks(doc_id, parent_block_uid)"
    yield "CREATE INDEX IF NOT EXISTS idx_doc_blocks_doc_heading ON doc_blocks(doc_id, derived_title_level, page_idx)"
    yield "CREATE INDEX IF NOT EXISTS idx_doc_blocks_doc_explain ON doc_blocks(doc_id, explain_for_block_uid)"
    yield """
    CREATE TABLE IF NOT EXISTS document_segments (
        id TEXT PRIMARY KEY,
        doc_id TEXT NOT NULL,
        library_id TEXT NOT NULL,
        strategy TEXT NOT NULL,
        item_type TEXT NOT NULL,
        title TEXT,
        content TEXT NOT NULL,
        meta_json TEXT,
        schema_version TEXT NOT NULL DEFAULT '1.0.0',
        order_index INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """
    yield ("CREATE INDEX IF NOT EXISTS idx_document_segments_doc_strategy "
           "ON document_segments (doc_id, strategy, item_type, order_index)")
    yield """
    CREATE TABLE IF NOT EXISTS doc_block_corrections (
        id TEXT PRIMARY KEY,
        doc_id TEXT NOT NULL,
        block_uid TEXT NOT NULL,
        operation_type TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """
    yield ("CREATE INDEX IF NOT EXISTS idx_doc_block_corrections_doc_block "
           "ON doc_block_corrections(doc_id, block_uid, created_at)")
    # ---- canonical ----
    yield """
    CREATE TABLE IF NOT EXISTS canonical_documents (
        doc_id TEXT PRIMARY KEY,
        library_id TEXT NOT NULL,
        title TEXT NOT NULL,
        source_file_name TEXT,
        source_file_type TEXT,
        schema_version TEXT,
        parse_version TEXT,
        language TEXT,
        page_count INTEGER NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT,
        updated_at TEXT
    )
    """
    yield "CREATE INDEX IF NOT EXISTS idx_canonical_documents_library ON canonical_documents(library_id)"
    yield """
    CREATE TABLE IF NOT EXISTS canonical_pages (
        doc_id TEXT NOT NULL,
        page_idx INTEGER NOT NULL,
        width DOUBLE PRECISION NOT NULL,
        height DOUBLE PRECISION NOT NULL,
        rotation INTEGER NOT NULL,
        image_path TEXT,
        printed_page_label TEXT,
        PRIMARY KEY (doc_id, page_idx)
    )
    """
    yield """
    CREATE TABLE IF NOT EXISTS canonical_blocks (
        block_id TEXT PRIMARY KEY,
        doc_id TEXT NOT NULL,
        page_idx INTEGER NOT NULL,
        block_type TEXT NOT NULL,
        text TEXT,
        text_clean TEXT,
        bbox_json TEXT,
        reading_order INTEGER NOT NULL,
        title_level INTEGER,
        section_path TEXT,
        source TEXT,
        source_ref TEXT,
        parent_block_id TEXT,
        inherited_chapter TEXT,
        entity_tags_json TEXT,
        conditions_json TEXT,
        exam_tags_json TEXT,
        clause_id TEXT,
        contd_target_id TEXT,
        image_assoc_id TEXT,
        table_merge_id TEXT,
        raw_type TEXT,
        page_bboxes_json TEXT,
        merged_from_json TEXT
    )
    """
    yield ("CREATE INDEX IF NOT EXISTS idx_canonical_blocks_doc_page "
           "ON canonical_blocks(doc_id, page_idx, reading_order)")
    yield ("CREATE INDEX IF NOT EXISTS idx_canonical_blocks_clause_id "
           "ON canonical_blocks(doc_id, clause_id)")
    yield """
    CREATE TABLE IF NOT EXISTS canonical_outlines (
        outline_id TEXT PRIMARY KEY,
        doc_id TEXT NOT NULL,
        level INTEGER NOT NULL,
        title TEXT NOT NULL,
        section_path TEXT,
        page_idx INTEGER NOT NULL,
        anchor_block_id TEXT,
        parent_outline_id TEXT
    )
    """
    yield """
    CREATE TABLE IF NOT EXISTS canonical_chunks (
        chunk_id TEXT PRIMARY KEY,
        doc_id TEXT NOT NULL,
        chunk_type TEXT NOT NULL,
        text TEXT,
        text_clean TEXT,
        token_count INTEGER NOT NULL,
        section_path TEXT,
        page_start INTEGER NOT NULL,
        page_end INTEGER NOT NULL,
        source_block_ids_json TEXT,
        citation_targets_json TEXT,
        version TEXT,
        inherited_chapter TEXT,
        entity_tags_json TEXT,
        conditions_json TEXT,
        exam_tags_json TEXT,
        clause_id TEXT
    )
    """
    yield ("CREATE INDEX IF NOT EXISTS idx_canonical_chunks_doc_type "
           "ON canonical_chunks(doc_id, chunk_type, page_start)")
    # text_clean 可能超 PG btree 单行上限（1/3 页 ≈ 2704 字节，长条款 chunk 实测 4376）：
    # 改前缀函数索引（500 字 ≈ 1500 字节 UTF8），保住 doc 内按 text_clean 前缀定位的用途
    yield ("CREATE INDEX IF NOT EXISTS idx_canonical_chunks_doc_text "
           "ON canonical_chunks(doc_id, (substring(text_clean for 500)))")
    yield ("CREATE INDEX IF NOT EXISTS idx_canonical_chunks_clause_id "
           "ON canonical_chunks(doc_id, clause_id)")
    # FTS：text_ngrams 由 Python 写入侧展开（与 SQLite 同一 build_cjk_ngram_text），
    # tsvector 生成列吃 text_ngrams（已含 section_path 的 bigram）+ section_path 原文。
    yield f"""
    CREATE TABLE IF NOT EXISTS canonical_chunk_fts (
        chunk_id TEXT PRIMARY KEY,
        doc_id TEXT NOT NULL,
        chunk_type TEXT NOT NULL DEFAULT '',
        section_path TEXT NOT NULL DEFAULT '',
        text_clean TEXT NOT NULL DEFAULT '',
        text_ngrams TEXT NOT NULL DEFAULT '',
        fts tsvector GENERATED ALWAYS AS (
            to_tsvector('simple', coalesce(text_ngrams, '') || ' ' || coalesce(section_path, ''))
        ) STORED
    )
    """
    yield "CREATE INDEX IF NOT EXISTS idx_canonical_chunk_fts ON canonical_chunk_fts USING gin (fts)"
    yield "CREATE INDEX IF NOT EXISTS idx_canonical_chunk_fts_doc ON canonical_chunk_fts(doc_id)"
    yield """
    CREATE TABLE IF NOT EXISTS canonical_tables (
        table_id TEXT PRIMARY KEY,
        doc_id TEXT NOT NULL,
        page_start INTEGER NOT NULL,
        page_end INTEGER NOT NULL,
        title TEXT,
        caption TEXT,
        bbox_json TEXT,
        page_bboxes_json TEXT,
        table_type TEXT,
        header_rows_json TEXT,
        body_rows_json TEXT,
        units_json TEXT,
        row_count INTEGER NOT NULL,
        col_count INTEGER NOT NULL,
        source_block_ids_json TEXT,
        summary TEXT,
        row_keys_json TEXT,
        text_chunks_json TEXT,
        version TEXT
    )
    """
    yield ("CREATE INDEX IF NOT EXISTS idx_canonical_tables_doc_type "
           "ON canonical_tables(doc_id, table_type, page_start)")
    yield """
    CREATE TABLE IF NOT EXISTS canonical_citation_targets (
        row_id TEXT PRIMARY KEY,
        doc_id TEXT NOT NULL,
        target_id TEXT NOT NULL,
        target_type TEXT NOT NULL,
        page_idx INTEGER NOT NULL,
        bbox_json TEXT,
        section_path TEXT,
        display_title TEXT,
        snippet TEXT,
        printed_page_label TEXT
    )
    """
    yield ("CREATE INDEX IF NOT EXISTS idx_canonical_citations_doc_target "
           "ON canonical_citation_targets(doc_id, target_id)")
    # ---- registry ----
    yield """
    CREATE TABLE IF NOT EXISTS library_registry (
        library_id  TEXT PRIMARY KEY,
        name        TEXT NOT NULL DEFAULT '',
        description TEXT NOT NULL DEFAULT '',
        group_name  TEXT NOT NULL,
        sqlite_file TEXT NOT NULL,
        collection  TEXT NOT NULL,
        status      TEXT NOT NULL DEFAULT 'active',
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    )
    """
    yield "CREATE INDEX IF NOT EXISTS idx_library_registry_group ON library_registry(group_name)"
    yield """
    CREATE TABLE IF NOT EXISTS library_groups (
        group_name   TEXT PRIMARY KEY,
        display_name TEXT NOT NULL DEFAULT '',
        created_at   TEXT NOT NULL,
        updated_at   TEXT NOT NULL
    )
    """
    # ---- parse_records（上传台账）----
    yield """
    CREATE TABLE IF NOT EXISTS parse_records (
        id BIGSERIAL PRIMARY KEY,
        doc_id TEXT NOT NULL,
        task_id TEXT NOT NULL,
        uploaded_by TEXT NOT NULL DEFAULT '',
        api_key_id INTEGER,
        file_name TEXT NOT NULL DEFAULT '',
        file_format TEXT NOT NULL DEFAULT '',
        file_size INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'queued',
        error TEXT,
        created_at TEXT NOT NULL,
        library_id TEXT NOT NULL DEFAULT 'default',
        stages TEXT NOT NULL DEFAULT ''
    )
    """
    yield "CREATE INDEX IF NOT EXISTS idx_pr_created ON parse_records(created_at DESC)"
    yield "CREATE INDEX IF NOT EXISTS idx_pr_uploaded ON parse_records(uploaded_by)"
    yield "CREATE INDEX IF NOT EXISTS idx_pr_status ON parse_records(status)"
    # ---- 向量记录（pgvector；collection_name 复刻 Qdrant 组隔离）----
    yield f"""
    CREATE TABLE IF NOT EXISTS vector_records (
        collection_name TEXT NOT NULL,
        record_id TEXT NOT NULL,
        doc_id TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        entity_id TEXT NOT NULL,
        content TEXT NOT NULL DEFAULT '',
        content_hash TEXT NOT NULL DEFAULT '',
        metadata_json TEXT NOT NULL DEFAULT '{{}}',
        embedding vector({dim}) NOT NULL,
        library_id TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (collection_name, record_id)
    )
    """
    yield ("CREATE INDEX IF NOT EXISTS idx_vector_records_collection_doc "
           "ON vector_records(collection_name, doc_id)")
    yield "CREATE INDEX IF NOT EXISTS idx_vector_records_library ON vector_records(collection_name, library_id)"
    yield (
        "CREATE INDEX IF NOT EXISTS idx_vector_records_hnsw "
        "ON vector_records USING hnsw (embedding vector_cosine_ops)"
    )
    # ---- kb_migration_tasks（迁移任务表；PG 档位下迁移工具本身禁用，表仅为 schema 完整）----
    yield """
    CREATE TABLE IF NOT EXISTS kb_migration_tasks (
        id TEXT PRIMARY KEY,
        op TEXT NOT NULL,
        params_json TEXT NOT NULL DEFAULT '{}',
        status TEXT NOT NULL DEFAULT 'pending',
        stage TEXT NOT NULL DEFAULT '',
        progress INTEGER NOT NULL DEFAULT 0,
        steps_json TEXT NOT NULL DEFAULT '[]',
        migrated_json TEXT NOT NULL DEFAULT '[]',
        preview_json TEXT,
        verify_json TEXT,
        error TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """


__all__ = [
    "KB_STACK_ENV",
    "PG_DSN_ENV",
    "PG_SENTINEL_DB_PATH",
    "PG_VECTOR_DIM_ENV",
    "PgConnection",
    "PgCursor",
    "PgRow",
    "STACK_LEGACY",
    "STACK_PG",
    "ensure_pg_ready",
    "is_pg",
    "kb_stack",
    "parse_pg_dsn",
    "pg_connect",
    "translate_sql",
    "vector_dimension",
]
