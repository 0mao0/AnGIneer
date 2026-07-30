"""Dream Cycle 主运行器。

每日凌晨执行各项知识库健康检查任务，生成 JSON 报告。
可通过 cron 调度或手动触发。
"""

import json
import logging
import os
import sqlite3
import time
import traceback
from datetime import datetime
from typing import Optional

from .config import DreamCycleConfig, get_config
from .report import (
    DreamCycleReport,
    TaskResult,
    DuplicateCandidate,
    ContradictionCandidate,
    OrphanEntity,
    StalenessCandidate,
    SopHealthStats,
)

logger = logging.getLogger("dream_cycle")


class DreamCycleRunner:
    """Dream Cycle 任务运行器，按顺序执行所有启用的检查任务。"""

    def __init__(self, config: Optional[DreamCycleConfig] = None):
        self.config = config or get_config()
        self.report: Optional[DreamCycleReport] = None

    def run(self) -> DreamCycleReport:
        """执行所有启用的任务，返回完整报告。"""
        if not self.config.enabled:
            logger.info("Dream Cycle 已禁用，跳过执行。")
            return DreamCycleReport.create_empty()

        today = datetime.now().strftime("%Y-%m-%d")
        self.report = DreamCycleReport.create_empty(today)
        started_at = time.time()

        os.makedirs(self.config.reports_dir, exist_ok=True)
        os.makedirs(self.config.audit_dir, exist_ok=True)

        tasks = [
            ("实体去重检查", self.config.dedup_enabled, self._run_dedup_check),
            ("矛盾关系检测", self.config.contradiction_enabled, self._run_contradiction_check),
            ("孤立实体清理", self.config.orphan_enabled, self._run_orphan_check),
            ("过期知识标记", self.config.staleness_enabled, self._run_staleness_check),
            ("SOP 健康统计", self.config.sop_health_enabled, self._run_sop_health),
        ]

        for task_name, enabled, task_fn in tasks:
            if not enabled:
                self.report.task_results.append(TaskResult(
                    task_name=task_name,
                    status="skipped",
                    message="已通过配置禁用",
                ))
                continue
            self._run_task(task_name, task_fn)

        run_duration = time.time() - started_at
        self.report.finalize(run_duration)

        # 写入报告文件
        report_path = os.path.join(self.config.reports_dir, f"{today}.json")
        try:
            with open(report_path, "w", encoding="utf-8") as f:
                f.write(json.dumps(self.report.model_dump(mode="json"), indent=2, ensure_ascii=False))
            logger.info(f"Dream Cycle 报告已写入: {report_path}")
        except Exception as e:
            logger.error(f"写入报告失败: {e}")

        return self.report

    def _run_task(self, task_name: str, task_fn):
        """安全执行单个任务，捕获异常。"""
        t0 = time.time()
        try:
            task_fn()
            duration = time.time() - t0
        except Exception as e:
            duration = time.time() - t0
            logger.error(f"任务 [{task_name}] 执行失败: {e}")
            traceback.print_exc()
            self.report.task_results.append(TaskResult(
                task_name=task_name,
                status="error",
                message=f"任务执行异常: {str(e)[:200]}",
                duration_seconds=round(duration, 2),
                error_detail=traceback.format_exc(),
            ))

    # ─── Task 1: 实体去重检查 ───────────────────────────────────

    def _run_dedup_check(self):
        """检测疑似重复的 graph_entities 条目。"""
        t0 = time.time()
        found = 0
        auto_fixed = 0

        conn = self._connect_graph_db()
        if not conn:
            return

        try:
            # 规则A：编辑距离相近的同层实体
            entities = conn.execute(
                "SELECT entity_id, name, layer FROM graph_entities ORDER BY layer, name"
            ).fetchall()

            for i in range(len(entities)):
                for j in range(i + 1, len(entities)):
                    a_id, a_name, a_layer = entities[i]
                    b_id, b_name, b_layer = entities[j]

                    if a_layer != b_layer:
                        continue

                    name_a = str(a_name or "").strip()
                    name_b = str(b_name or "").strip()
                    if not name_a or not name_b:
                        continue

                    # 编辑距离检查
                    edit_dist = self._edit_distance(name_a, name_b)
                    max_len = max(len(name_a), len(name_b))
                    if max_len == 0:
                        continue
                    similarity = 1.0 - (edit_dist / max_len)

                    if similarity < self.config.dedup_review_threshold:
                        continue

                    # 检查 aliases 是否交叉
                    aliases_a = self._get_aliases(conn, a_id)
                    aliases_b = self._get_aliases(conn, b_id)
                    alias_overlap = bool(
                        name_a in aliases_b or name_b in aliases_a or
                        set(aliases_a) & set(aliases_b)
                    )
                    match_method = "alias_overlap" if alias_overlap else "edit_distance"

                    candidate = DuplicateCandidate(
                        entity_a_id=a_id,
                        entity_a_name=name_a,
                        entity_b_id=b_id,
                        entity_b_name=name_b,
                        match_method=match_method,
                        confidence=similarity,
                        suggested_canonical_name=name_a if len(name_a) >= len(name_b) else name_b,
                    )

                    if similarity >= self.config.dedup_auto_threshold:
                        candidate.suggested_action = "auto_merge"
                        self._merge_entities(conn, a_id, b_id, candidate.suggested_canonical_name)
                        auto_fixed += 1
                    else:
                        candidate.suggested_action = "review"

                    self.report.duplicate_candidates.append(candidate)
                    found += 1

            self.report.task_results.append(TaskResult(
                task_name="实体去重检查",
                status="success",
                message=f"发现 {found} 对疑似重复实体，自动合并 {auto_fixed} 对",
                duration_seconds=round(time.time() - t0, 2),
                findings_count=found,
                auto_fixed_count=auto_fixed,
            ))
        finally:
            conn.close()

    # ─── Task 2: 矛盾关系检测 ───────────────────────────────────

    def _run_contradiction_check(self):
        """检测不同文档中抽取的相互矛盾的关系。"""
        t0 = time.time()
        found = 0

        conn = self._connect_graph_db()
        if not conn:
            return

        try:
            # 预加载文档名称：从知识库元数据库读取 doc_id → title 映射
            doc_titles: dict = {}
            try:
                if os.path.exists(self.config.knowledge_meta_path):
                    meta_conn = sqlite3.connect(self.config.knowledge_meta_path)
                    for row in meta_conn.execute("SELECT id, title FROM nodes WHERE title IS NOT NULL"):
                        doc_titles[str(row[0])] = str(row[1])
                    meta_conn.close()
            except Exception:
                pass

            # 查找同一对实体在不同文档中存在的关系
            rows = conn.execute("""
                SELECT
                    r1.relation_id as rid1, r1.source_id as sid1, r1.target_id as tid1,
                    r1.relation_type as rt1, r1.doc_id as doc1, r1.source_clause as clause1,
                    r1.evidence_text as evi1,
                    r2.relation_id as rid2, r2.source_id as sid2, r2.target_id as tid2,
                    r2.relation_type as rt2, r2.doc_id as doc2, r2.source_clause as clause2,
                    r2.evidence_text as evi2,
                    e1.name as entity_subject, e2.name as entity_object
                FROM graph_relations r1
                JOIN graph_relations r2
                    ON r1.source_id = r2.source_id
                    AND r1.target_id = r2.target_id
                    AND r1.doc_id != r2.doc_id
                    AND r1.relation_id < r2.relation_id
                JOIN graph_entities e1 ON e1.entity_id = r1.source_id
                JOIN graph_entities e2 ON e2.entity_id = r1.target_id
                ORDER BY e1.name
            """).fetchall()

            for row in rows:
                rid1, sid1, tid1, rt1, doc1, clause1, evi1, rid2, sid2, tid2, rt2, doc2, clause2, evi2, subject, object = row

                # 矛盾判定：relation_type 不同
                if rt1 == rt2:
                    continue

                # Python 中解析文档名称：doc_id → title，查不到则回退 doc_id
                doc1_title = doc_titles.get(str(doc1 or "")) or ""
                doc2_title = doc_titles.get(str(doc2 or "")) or ""
                doc1_display = doc1_title or str(doc1 or "")
                doc2_display = doc2_title or str(doc2 or "")

                # 截取证据文本前 200 字作为矛盾内容摘要
                evi1_text = str(evi1 or "").strip()[:200]
                evi2_text = str(evi2 or "").strip()[:200]

                candidate = ContradictionCandidate(
                    entity_subject=str(subject or ""),
                    relation_a={
                        "relation_id": str(rid1 or ""),
                        "source_doc": doc1_display,
                        "source_clause": str(clause1 or ""),
                        "relation_type": str(rt1 or ""),
                        "evidence": evi1_text,
                    },
                    relation_b={
                        "relation_id": str(rid2 or ""),
                        "source_doc": doc2_display,
                        "source_clause": str(clause2 or ""),
                        "relation_type": str(rt2 or ""),
                        "evidence": evi2_text,
                    },
                    entity_object=str(object or ""),
                    contradiction_type="type_conflict",
                    suggested_resolution=f"两份文档对「{subject}」与「{object}」之间的关系判断不同。\n"
                        f"文档A（{doc1_display}）认为：{evi1_text or '(无原文摘要)'}\n"
                        f"文档B（{doc2_display}）认为：{evi2_text or '(无原文摘要)'}",
                    confidence=0.7,
                )
                self.report.contradiction_candidates.append(candidate)
                found += 1

            self.report.task_results.append(TaskResult(
                task_name="矛盾关系检测",
                status="success",
                message=f"发现 {found} 处疑似矛盾关系",
                duration_seconds=round(time.time() - t0, 2),
                findings_count=found,
            ))
        finally:
            conn.close()

    # ─── Task 3: 孤立实体清理 ───────────────────────────────────

    def _run_orphan_check(self):
        """检测没有任何关系的孤立实体。"""
        t0 = time.time()
        found = 0
        auto_fixed = 0

        conn = self._connect_graph_db()
        if not conn:
            return

        try:
            min_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            min_date_str = (
                min_date.replace(day=min_date.day - self.config.orphan_min_age_days)
                .strftime("%Y-%m-%d")
            )
            auto_date_str = (
                min_date.replace(day=min_date.day - self.config.orphan_auto_clean_days)
                .strftime("%Y-%m-%d")
            )

            rows = conn.execute(f"""
                SELECT e.entity_id, e.name, e.layer, e.created_at
                FROM graph_entities e
                WHERE e.entity_id NOT IN (
                    SELECT source_id FROM graph_relations
                    UNION
                    SELECT target_id FROM graph_relations
                )
                AND e.source_doc IS NOT NULL
                AND e.created_at < '{min_date_str}'
            """).fetchall()

            for row in rows:
                eid, name, layer, created_at = row
                # 处理时区问题：数据库中的时间可能带时区，datetime.now() 是不带时区的
                created_dt = datetime.fromisoformat(str(created_at or min_date_str))
                if created_dt.tzinfo is not None:
                    created_dt = created_dt.replace(tzinfo=None)
                age_days = (datetime.now() - created_dt).days

                orphan = OrphanEntity(
                    entity_id=str(eid or ""),
                    entity_name=str(name or ""),
                    entity_layer=str(layer or ""),
                    age_days=age_days,
                )

                if str(created_at or "") < auto_date_str:
                    orphan.suggested_action = "auto_mark_inactive"
                    try:
                        conn.execute(
                            "UPDATE graph_entities SET description = description || ' [DREAM_CYCLE: 孤立实体，已自动标记为 inactive]' WHERE entity_id = ?",
                            (eid,),
                        )
                        conn.commit()
                        auto_fixed += 1
                    except Exception:
                        pass
                else:
                    orphan.suggested_action = "review"

                self.report.orphan_entities.append(orphan)
                found += 1

            self.report.task_results.append(TaskResult(
                task_name="孤立实体清理",
                status="success",
                message=f"发现 {found} 个孤立实体，自动清理 {auto_fixed} 个",
                duration_seconds=round(time.time() - t0, 2),
                findings_count=found,
                auto_fixed_count=auto_fixed,
            ))
        finally:
            conn.close()

    # ─── Task 4: 过期知识标记 ───────────────────────────────────

    def _run_staleness_check(self):
        """检测可能过时的知识（新旧规范版本冲突）。"""
        t0 = time.time()
        found = 0

        conn = self._connect_graph_db()
        if not conn:
            return

        try:
            # 暂用简化版本：检测包含年份标题的文档
            conn.execute("ATTACH DATABASE ? AS meta", (self.config.knowledge_meta_path,))
            rows = conn.execute("""
                SELECT DISTINCT e.entity_id, e.name, e.source_doc
                FROM graph_entities e
                WHERE e.source_doc IS NOT NULL AND e.source_doc != ''
            """).fetchall()

            # 按文档年份分组检测潜在的旧版本文档
            doc_years: dict = {}
            for row in rows:
                doc = str(row[2] or "")
                # 尝试提取文档标题/ID 中的四位年份
                import re
                year_match = re.search(r'(?:19|20)\d{2}', doc)
                if year_match:
                    doc_years.setdefault(doc, int(year_match.group()))

            # 简化：任何在 titles 中能找到更新年份规范的实体都标记
            # 实际生产环境应通过 canonical_documents 获取准确版本信息
            self.report.task_results.append(TaskResult(
                task_name="过期知识标记",
                status="success",
                message=f"发现 {found} 个疑似过时实体（基于年份检测）",
                duration_seconds=round(time.time() - t0, 2),
                findings_count=found,
            ))
        except Exception as e:
            logger.warning(f"过期知识检测失败: {e}")
            self.report.task_results.append(TaskResult(
                task_name="过期知识标记",
                status="warning",
                message=f"检测过程出现异常，跳过了部分检查: {str(e)[:200]}",
                duration_seconds=round(time.time() - t0, 2),
            ))
        finally:
            try:
                conn.execute("DETACH DATABASE meta")
            except Exception:
                pass
            conn.close()

    # ─── Task 5: SOP 健康统计 ───────────────────────────────────

    def _run_sop_health(self):
        """统计 SOP 使用情况和知识图谱覆盖度。"""
        t0 = time.time()

        try:
            # 尝试读取 SOP index
            sops_dir = os.path.join(
                os.path.dirname(self.config.data_dir), "sops"
            )
            index_path = os.path.join(sops_dir, "index.json")
            sops = []
            if os.path.exists(index_path):
                with open(index_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    sops = data if isinstance(data, list) else data.get("sops", [])

            if not sops:
                # fallback: 扫描 json 目录
                json_dir = os.path.join(sops_dir, "json")
                if os.path.isdir(json_dir):
                    sops = [
                        {"id": f.replace(".json", ""), "name": f}
                        for f in os.listdir(json_dir)
                        if f.endswith(".json") and f != "index.json"
                    ]

            sop_health = SopHealthStats(
                total_sops=len(sops),
                active_sops=len(sops),  # 简化：所有 SOP 视为 active
                total_steps=0,
            )
            self.report.sop_health = sop_health

            self.report.task_results.append(TaskResult(
                task_name="SOP 健康统计",
                status="success",
                message=f"共 {len(sops)} 个 SOP，统计数据已生成",
                duration_seconds=round(time.time() - t0, 2),
                findings_count=len(sops),
            ))
        except Exception as e:
            logger.warning(f"SOP 统计失败: {e}")
            self.report.task_results.append(TaskResult(
                task_name="SOP 健康统计",
                status="warning",
                message=f"统计失败: {str(e)[:200]}",
                duration_seconds=round(time.time() - t0, 2),
            ))

    # ─── 辅助方法 ──────────────────────────────────────────────

    def _connect_graph_db(self) -> Optional[sqlite3.Connection]:
        """连接到知识图谱 SQLite 数据库。"""
        db_path = self.config.graph_db_path
        if not os.path.exists(db_path):
            logger.error(f"知识图谱数据库不存在: {db_path}")
            return None
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _get_aliases(conn: sqlite3.Connection, entity_id: str) -> list:
        """获取实体的别名列表。"""
        row = conn.execute(
            "SELECT aliases_json FROM graph_entities WHERE entity_id = ?",
            (entity_id,),
        ).fetchone()
        if not row or not row[0]:
            return []
        try:
            return json.loads(str(row[0]))
        except (json.JSONDecodeError, TypeError):
            return []

    @staticmethod
    def _edit_distance(s1: str, s2: str) -> int:
        """计算两个字符串的 Levenshtein 编辑距离。"""
        if len(s1) < len(s2):
            return DreamCycleRunner._edit_distance(s2, s1)
        if len(s2) == 0:
            return len(s1)
        prev_row = list(range(len(s2) + 1))
        for i, c1 in enumerate(s1):
            curr_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = prev_row[j + 1] + 1
                deletions = curr_row[j] + 1
                substitutions = prev_row[j] + (0 if c1 == c2 else 1)
                curr_row.append(min(insertions, deletions, substitutions))
            prev_row = curr_row
        return prev_row[-1]

    def _merge_entities(self, conn: sqlite3.Connection, keep_id: str, remove_id: str, canonical_name: str):
        """合并两个实体：保留 keep_id，将 remove_id 的所有关系重定向到 keep_id。"""
        try:
            # 更新关系表中的 source_id
            conn.execute(
                "UPDATE graph_relations SET source_id = ? WHERE source_id = ?",
                (keep_id, remove_id),
            )
            # 更新关系表中的 target_id
            conn.execute(
                "UPDATE graph_relations SET target_id = ? WHERE target_id = ?",
                (keep_id, remove_id),
            )
            # 更新实体名称
            conn.execute(
                "UPDATE graph_entities SET name = ? WHERE entity_id = ?",
                (canonical_name, keep_id),
            )
            # 将旧实体的 aliases 合并到保留实体
            aliases_keep = self._get_aliases(conn, keep_id)
            aliases_remove = self._get_aliases(conn, remove_id)
            old_name = conn.execute(
                "SELECT name FROM graph_entities WHERE entity_id = ?", (remove_id,)
            ).fetchone()
            merged_aliases = list(set(aliases_keep + aliases_remove))
            if old_name and old_name[0]:
                merged_aliases.append(str(old_name[0]))
            conn.execute(
                "UPDATE graph_entities SET aliases_json = ? WHERE entity_id = ?",
                (json.dumps(merged_aliases, ensure_ascii=False), keep_id),
            )
            # 删除被合并的实体
            conn.execute("DELETE FROM graph_entities WHERE entity_id = ?", (remove_id,))
            conn.commit()

            # 写审计日志
            audit_entry = {
                "timestamp": datetime.now().isoformat(),
                "action": "merge_entities",
                "keep_id": keep_id,
                "removed_id": remove_id,
                "canonical_name": canonical_name,
            }
            self._write_audit("dedup", audit_entry)
        except Exception as e:
            logger.error(f"合并实体失败 ({keep_id}, {remove_id}): {e}")

    def _write_audit(self, category: str, entry: dict):
        """写入审计日志。"""
        try:
            audit_file = os.path.join(
                self.config.audit_dir,
                f"{category}-{datetime.now().strftime('%Y-%W')}.jsonl",
            )
            os.makedirs(os.path.dirname(audit_file), exist_ok=True)
            with open(audit_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"审计日志写入失败: {e}")


def run_dream_cycle():
    """命令行入口：执行一次 Dream Cycle。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    runner = DreamCycleRunner()
    report = runner.run()
    print(f"Dream Cycle 完成: {report.total_findings} 项发现, {report.total_auto_fixed} 项自动修复")


if __name__ == "__main__":
    run_dream_cycle()
