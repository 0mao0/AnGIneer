import json
import os
import sqlite3
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sop_core.research.contracts import (
    EvalDraftRecord,
    ResearchCandidateRecord,
    ResearchGapRecord,
    ResearchProjectCreate,
    ResearchProjectRecord,
    ResearchRunRecord,
    ResearchRunStart,
    ResearchRunSummary,
    SopDraftRecord,
)

_LOCAL: Any = None


def _get_thread_local():
    global _LOCAL
    if _LOCAL is None:
        import threading
        _LOCAL = threading.local()
    return _LOCAL


class ResearchStore:
    def __init__(self, base_dir: str):
        self._base_dir = base_dir
        self._db_path = os.path.join(base_dir, "data", "sops", "research_meta.sqlite")
        self._artifact_root = os.path.join(base_dir, "data", "sops", "research_runs")

    def _get_conn(self) -> sqlite3.Connection:
        local = _get_thread_local()
        key = f"research_conn_{id(self)}"
        conn = getattr(local, key, None)
        if conn is None:
            os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            setattr(local, key, conn)
        return conn

    def init_db(self) -> None:
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS research_project (
                project_id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT '',
                library_id TEXT NOT NULL DEFAULT '',
                doc_id TEXT NOT NULL DEFAULT '',
                doc_title TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'created',
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS research_run (
                run_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                progress REAL NOT NULL DEFAULT 0.0,
                stage TEXT NOT NULL DEFAULT '',
                stage_message TEXT NOT NULL DEFAULT '',
                stage_current INTEGER NOT NULL DEFAULT 0,
                stage_total INTEGER NOT NULL DEFAULT 0,
                stage_detail TEXT NOT NULL DEFAULT '',
                started_at TEXT NOT NULL DEFAULT '',
                finished_at TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS research_candidate (
                candidate_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL DEFAULT '',
                section_path TEXT NOT NULL DEFAULT '',
                candidate_type TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                evidence_block_ids TEXT NOT NULL DEFAULT '[]',
                raw_score REAL NOT NULL DEFAULT 0.0,
                expected_inputs TEXT,
                expected_outputs TEXT
            );

            CREATE TABLE IF NOT EXISTS research_gap (
                gap_id TEXT PRIMARY KEY,
                candidate_id TEXT NOT NULL DEFAULT '',
                gap_type TEXT NOT NULL DEFAULT '',
                question TEXT NOT NULL DEFAULT '',
                answer TEXT NOT NULL DEFAULT '',
                severity TEXT NOT NULL DEFAULT 'medium'
            );

            CREATE TABLE IF NOT EXISTS sop_draft (
                draft_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL DEFAULT '',
                candidate_id TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                sop_id_suggested TEXT NOT NULL DEFAULT '',
                json_path TEXT NOT NULL DEFAULT '',
                review_status TEXT NOT NULL DEFAULT 'generated',
                score_total REAL NOT NULL DEFAULT 0.0,
                score_rule REAL NOT NULL DEFAULT 0.0,
                score_model REAL NOT NULL DEFAULT 0.0,
                evidence_block_ids TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS eval_draft (
                draft_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL DEFAULT '',
                source_sop_draft_id TEXT NOT NULL DEFAULT '',
                dataset_title TEXT NOT NULL DEFAULT '',
                question_count INTEGER NOT NULL DEFAULT 0,
                json_path TEXT NOT NULL DEFAULT '',
                review_status TEXT NOT NULL DEFAULT 'generated',
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS research_review_log (
                review_id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_type TEXT NOT NULL DEFAULT '',
                target_id TEXT NOT NULL DEFAULT '',
                decision TEXT NOT NULL DEFAULT '',
                reviewer TEXT NOT NULL DEFAULT '',
                comment TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT ''
            );

            CREATE INDEX IF NOT EXISTS idx_research_run_project ON research_run(project_id);
            CREATE INDEX IF NOT EXISTS idx_research_candidate_run ON research_candidate(run_id);
            CREATE INDEX IF NOT EXISTS idx_research_gap_candidate ON research_gap(candidate_id);
            CREATE INDEX IF NOT EXISTS idx_sop_draft_run ON sop_draft(run_id);
            CREATE INDEX IF NOT EXISTS idx_eval_draft_run ON eval_draft(run_id);
            CREATE INDEX IF NOT EXISTS idx_review_log_target ON research_review_log(target_type, target_id);
        """)
        self._migrate_run_columns(conn)
        conn.commit()

    def _migrate_run_columns(self, conn: sqlite3.Connection) -> None:
        existing = {row[1] for row in conn.execute("PRAGMA table_info(research_run)").fetchall()}
        for col, decl in [
            ("stage_current", "INTEGER NOT NULL DEFAULT 0"),
            ("stage_total", "INTEGER NOT NULL DEFAULT 0"),
            ("stage_detail", "TEXT NOT NULL DEFAULT ''"),
        ]:
            if col not in existing:
                conn.execute(f"ALTER TABLE research_run ADD COLUMN {col} {decl}")

    def get_artifact_root(self, run_id: str) -> str:
        return os.path.join(self._artifact_root, run_id)

    def create_project(self, payload: ResearchProjectCreate) -> ResearchProjectRecord:
        now = datetime.now().isoformat()
        project_id = uuid.uuid4().hex[:12]
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO research_project
               (project_id, title, library_id, doc_id, doc_title, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 'created', ?, ?)""",
            (project_id, payload.title, payload.library_id, payload.doc_id, payload.doc_title, now, now),
        )
        conn.commit()
        return ResearchProjectRecord(
            project_id=project_id,
            title=payload.title,
            library_id=payload.library_id,
            doc_id=payload.doc_id,
            doc_title=payload.doc_title,
            status="created",
            created_at=now,
            updated_at=now,
        )

    def list_projects(self) -> List[ResearchProjectRecord]:
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM research_project ORDER BY created_at DESC").fetchall()
        return [ResearchProjectRecord(**dict(row)) for row in rows]

    def get_project(self, project_id: str) -> Optional[ResearchProjectRecord]:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM research_project WHERE project_id = ?", (project_id,)).fetchone()
        if not row:
            return None
        return ResearchProjectRecord(**dict(row))

    def create_run(self, payload: ResearchRunStart) -> ResearchRunRecord:
        now = datetime.now().isoformat()
        run_id = uuid.uuid4().hex[:12]
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO research_run
               (run_id, project_id, status, progress, stage, stage_message, started_at, finished_at, error)
               VALUES (?, ?, 'running', 0.0, '', '', ?, '', '')""",
            (run_id, payload.project_id, now),
        )
        conn.commit()
        return ResearchRunRecord(
            run_id=run_id,
            project_id=payload.project_id,
            status="running",
            progress=0.0,
            stage="",
            stage_message="",
            stage_current=0,
            stage_total=0,
            stage_detail="",
            started_at=now,
            finished_at="",
            error="",
        )

    def list_runs(self, project_id: Optional[str] = None) -> List[ResearchRunRecord]:
        conn = self._get_conn()
        if project_id:
            rows = conn.execute(
                "SELECT * FROM research_run WHERE project_id = ? ORDER BY started_at DESC",
                (project_id,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM research_run ORDER BY started_at DESC").fetchall()
        return [ResearchRunRecord(**dict(row)) for row in rows]

    # 一次性聚合 run + 候选/草稿/批准计数，避免 routes 层 N+1 查询
    _RUN_SUMMARY_SELECT = """
        SELECT r.*,
            (SELECT COUNT(*) FROM research_candidate c WHERE c.run_id = r.run_id) AS candidate_count,
            (SELECT COUNT(*) FROM sop_draft sd WHERE sd.run_id = r.run_id) AS sop_draft_count,
            (SELECT COUNT(*) FROM eval_draft ed WHERE ed.run_id = r.run_id) AS eval_draft_count,
            ((SELECT COUNT(*) FROM sop_draft sd WHERE sd.run_id = r.run_id AND sd.review_status = 'approved')
             + (SELECT COUNT(*) FROM eval_draft ed WHERE ed.run_id = r.run_id AND ed.review_status = 'approved')) AS approval_count
        FROM research_run r
    """

    def _row_to_run_with_summary(self, row: sqlite3.Row) -> tuple:
        d = dict(row)
        run = ResearchRunRecord(
            run_id=d["run_id"],
            project_id=d["project_id"],
            status=d["status"],
            progress=d["progress"],
            stage=d["stage"],
            stage_message=d["stage_message"],
            stage_current=d["stage_current"],
            stage_total=d["stage_total"],
            stage_detail=d["stage_detail"],
            started_at=d["started_at"],
            finished_at=d["finished_at"],
            error=d["error"],
        )
        summary = ResearchRunSummary(
            run_id=d["run_id"],
            project_id=d["project_id"],
            status=d["status"],
            stage=d["stage"],
            progress=d["progress"],
            candidate_count=d["candidate_count"],
            sop_draft_count=d["sop_draft_count"],
            eval_draft_count=d["eval_draft_count"],
            approval_count=d["approval_count"],
        )
        return run, summary

    def list_runs_with_summary(self, project_id: Optional[str] = None) -> List[tuple]:
        conn = self._get_conn()
        if project_id:
            rows = conn.execute(
                self._RUN_SUMMARY_SELECT + " WHERE r.project_id = ? ORDER BY r.started_at DESC",
                (project_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                self._RUN_SUMMARY_SELECT + " ORDER BY r.started_at DESC"
            ).fetchall()
        return [self._row_to_run_with_summary(row) for row in rows]

    def get_run_with_summary(self, run_id: str) -> Optional[tuple]:
        conn = self._get_conn()
        row = conn.execute(
            self._RUN_SUMMARY_SELECT + " WHERE r.run_id = ?",
            (run_id,),
        ).fetchone()
        if not row:
            return None
        return self._row_to_run_with_summary(row)

    def get_run(self, run_id: str) -> Optional[ResearchRunRecord]:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM research_run WHERE run_id = ?", (run_id,)).fetchone()
        if not row:
            return None
        return ResearchRunRecord(**dict(row))

    def update_run(self, run_id: str, **updates: Any) -> Optional[ResearchRunRecord]:
        allowed = {"status", "progress", "stage", "stage_message", "stage_current",
                   "stage_total", "stage_detail", "started_at", "finished_at", "error"}
        fields = [k for k in updates if k in allowed and updates[k] is not None]
        if not fields:
            return self.get_run(run_id)
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = [updates[k] for k in fields] + [run_id]
        conn = self._get_conn()
        conn.execute(f"UPDATE research_run SET {set_clause} WHERE run_id = ?", values)
        conn.commit()
        return self.get_run(run_id)

    def insert_candidates(self, run_id: str, candidates: List[ResearchCandidateRecord]) -> None:
        conn = self._get_conn()
        for c in candidates:
            conn.execute(
                """INSERT OR REPLACE INTO research_candidate
                   (candidate_id, run_id, section_path, candidate_type, title, summary,
                    evidence_block_ids, raw_score, expected_inputs, expected_outputs)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    c.candidate_id,
                    run_id,
                    c.section_path,
                    c.candidate_type,
                    c.title,
                    c.summary,
                    json.dumps(c.evidence_block_ids, ensure_ascii=False),
                    c.raw_score,
                    json.dumps(c.expected_inputs, ensure_ascii=False) if c.expected_inputs is not None else None,
                    json.dumps(c.expected_outputs, ensure_ascii=False) if c.expected_outputs is not None else None,
                ),
            )
        conn.commit()

    def list_candidates(self, run_id: str) -> List[ResearchCandidateRecord]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM research_candidate WHERE run_id = ? ORDER BY raw_score DESC",
            (run_id,),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["evidence_block_ids"] = json.loads(item.get("evidence_block_ids") or "[]")
            item["expected_inputs"] = json.loads(item["expected_inputs"]) if item.get("expected_inputs") else None
            item["expected_outputs"] = json.loads(item["expected_outputs"]) if item.get("expected_outputs") else None
            result.append(ResearchCandidateRecord(**item))
        return result

    def insert_gaps(self, candidate_id: str, gaps: List[ResearchGapRecord]) -> None:
        conn = self._get_conn()
        for g in gaps:
            conn.execute(
                """INSERT OR REPLACE INTO research_gap
                   (gap_id, candidate_id, gap_type, question, answer, severity)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (g.gap_id, candidate_id, g.gap_type, g.question, g.answer, g.severity),
            )
        conn.commit()

    def list_gaps(self, candidate_id: str) -> List[ResearchGapRecord]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM research_gap WHERE candidate_id = ? ORDER BY gap_id",
            (candidate_id,),
        ).fetchall()
        return [ResearchGapRecord(**dict(row)) for row in rows]

    def create_sop_draft(self, record: SopDraftRecord) -> SopDraftRecord:
        now = datetime.now().isoformat()
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO sop_draft
               (draft_id, run_id, candidate_id, title, sop_id_suggested, json_path,
                review_status, score_total, score_rule, score_model,
                evidence_block_ids, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.draft_id,
                record.run_id,
                record.candidate_id,
                record.title,
                record.sop_id_suggested,
                record.json_path,
                record.review_status,
                record.score_total,
                record.score_rule,
                record.score_model,
                json.dumps(record.evidence_block_ids, ensure_ascii=False),
                record.created_at or now,
                record.updated_at or now,
            ),
        )
        conn.commit()
        return record

    def list_sop_drafts(self, run_id: str) -> List[SopDraftRecord]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM sop_draft WHERE run_id = ? ORDER BY created_at DESC",
            (run_id,),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["evidence_block_ids"] = json.loads(item.get("evidence_block_ids") or "[]")
            result.append(SopDraftRecord(**item))
        return result

    def get_sop_draft(self, draft_id: str) -> Optional[SopDraftRecord]:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM sop_draft WHERE draft_id = ?", (draft_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["evidence_block_ids"] = json.loads(item.get("evidence_block_ids") or "[]")
        return SopDraftRecord(**item)

    def update_sop_draft(self, draft_id: str, **updates: Any) -> Optional[SopDraftRecord]:
        allowed = {
            "title", "sop_id_suggested", "json_path", "review_status",
            "score_total", "score_rule", "score_model", "evidence_block_ids",
        }
        conn = self._get_conn()
        set_clauses = []
        values = []
        for k in allowed:
            if k in updates and updates[k] is not None:
                if k == "evidence_block_ids":
                    set_clauses.append("evidence_block_ids = ?")
                    values.append(json.dumps(updates[k], ensure_ascii=False))
                else:
                    set_clauses.append(f"{k} = ?")
                    values.append(updates[k])
        if not set_clauses:
            return self.get_sop_draft(draft_id)
        set_clauses.append("updated_at = ?")
        values.append(datetime.now().isoformat())
        values.append(draft_id)
        conn.execute(f"UPDATE sop_draft SET {', '.join(set_clauses)} WHERE draft_id = ?", values)
        conn.commit()
        return self.get_sop_draft(draft_id)

    def create_eval_draft(self, record: EvalDraftRecord) -> EvalDraftRecord:
        now = datetime.now().isoformat()
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO eval_draft
               (draft_id, run_id, source_sop_draft_id, dataset_title, question_count,
                json_path, review_status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.draft_id,
                record.run_id,
                record.source_sop_draft_id,
                record.dataset_title,
                record.question_count,
                record.json_path,
                record.review_status,
                record.created_at or now,
                record.updated_at or now,
            ),
        )
        conn.commit()
        return record

    def list_eval_drafts(self, run_id: str) -> List[EvalDraftRecord]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM eval_draft WHERE run_id = ? ORDER BY created_at DESC",
            (run_id,),
        ).fetchall()
        return [EvalDraftRecord(**dict(row)) for row in rows]

    def get_eval_draft(self, draft_id: str) -> Optional[EvalDraftRecord]:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM eval_draft WHERE draft_id = ?", (draft_id,)).fetchone()
        if not row:
            return None
        return EvalDraftRecord(**dict(row))

    def update_eval_draft(self, draft_id: str, **updates: Any) -> Optional[EvalDraftRecord]:
        allowed = {
            "source_sop_draft_id", "dataset_title", "question_count",
            "json_path", "review_status",
        }
        conn = self._get_conn()
        set_clauses = []
        values = []
        for k in allowed:
            if k in updates and updates[k] is not None:
                set_clauses.append(f"{k} = ?")
                values.append(updates[k])
        if not set_clauses:
            return self.get_eval_draft(draft_id)
        set_clauses.append("updated_at = ?")
        values.append(datetime.now().isoformat())
        values.append(draft_id)
        conn.execute(f"UPDATE eval_draft SET {', '.join(set_clauses)} WHERE draft_id = ?", values)
        conn.commit()
        return self.get_eval_draft(draft_id)

    def log_review(self, target_type: str, target_id: str, decision: str, reviewer: str, comment: str = "") -> None:
        now = datetime.now().isoformat()
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO research_review_log
               (target_type, target_id, decision, reviewer, comment, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (target_type, target_id, decision, reviewer, comment, now),
        )
        conn.commit()
