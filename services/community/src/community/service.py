"""community 服务层：树装配、只读代理、投稿校验。路由只做 HTTP 壳，逻辑在此。

依赖注入形态照 chat-history：构造时收 store / eval_source / sop_source，
测试注入假对象即可全链路跑，不碰真实 sqlite / 网络。
"""
import os
from typing import Any, Dict, List, Optional, Tuple

from community import models
from community.sources import eval_source, sop_source as sop_source_mod
from community.store import CommunityStore


def _show_gold_default() -> bool:
    """gold 是否公开（§14-1 未决项的开关）：默认关，仅本地对照验证时置 1。"""
    return (os.getenv("COMMUNITY_SHOW_GOLD") or "").strip() in ("1", "true", "True")


def _visibility() -> str:
    """投稿可见性（设计 §7.4）：open=即时公开上树 / pool=只收不展（关不删数据，随时可开回）。"""
    raw = (os.getenv("COMMUNITY_SUBMISSION_VISIBILITY") or "").strip().lower()
    return raw if raw in ("open", "pool") else "open"


def _daily_limit() -> int:
    raw = (os.getenv("COMMUNITY_DAILY_LIMIT") or "").strip()
    if raw:
        try:
            return max(int(raw), 1)
        except ValueError:
            pass
    return models.DEFAULT_DAILY_LIMIT


class SubmissionError(Exception):
    """投稿校验失败：status 直接映射 HTTP 码（400 载荷不合法 / 404 目标不存在 / 429 超频）。"""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


class CommunityService:
    def __init__(
        self,
        store: Optional[CommunityStore] = None,
        *,
        eval_src=None,
        sop_src=None,
    ):
        self.store = store or CommunityStore()
        self.eval_src = eval_src or eval_source
        self.sop_src = sop_src or sop_source_mod.default_source()

    # ---- 左树（节点 + 条目一次拉齐） ----

    def get_tree(self, scope: str) -> Dict[str, Any]:
        nodes = [models.node_out(n) for n in self.store.list_nodes(scope)]
        items: List[Dict[str, Any]] = []
        if scope == models.SCOPE_EVAL:
            items.extend(self._official_eval_items())
            if _visibility() == "open":  # pool 档：投稿仍在库、不回树（A9）
                items.extend(self._user_dataset_items())
        elif scope == models.SCOPE_SOP:
            items.extend(self._official_sop_items())
        return {"scope": scope, "nodes": nodes, "items": items}

    def _official_eval_items(self) -> List[Dict[str, Any]]:
        bindings = {b["ref_id"]: b["node_id"] for b in self.store.list_bindings(models.SCOPE_EVAL)}
        if not bindings:
            return []
        out: List[Dict[str, Any]] = []
        for brief in self.eval_src.list_dataset_briefs():
            node_id = bindings.get(brief["dataset_id"])
            if not node_id:
                continue  # 未绑定 = 不公开（公开范围只由 community_binding 决定）
            out.append(models.tree_item(
                origin="official", ref_id=brief["dataset_id"], node_id=node_id,
                kind=models.KIND_DATASET, title=brief["title"],
                subtitle=brief.get("description", ""),
                question_count=brief.get("question_count"),
            ))
        return out

    def _user_dataset_items(self) -> List[Dict[str, Any]]:
        rows, _ = self.store.list_submissions(scope_id=models.SCOPE_EVAL, kinds=[models.KIND_DATASET])
        out: List[Dict[str, Any]] = []
        for row in rows:
            payload = row.get("payload") or {}
            items = payload.get("items") if isinstance(payload.get("items"), list) else []
            out.append(models.tree_item(
                origin="user", ref_id=row["submission_id"], node_id=row.get("node_id") or "",
                kind=models.KIND_DATASET, title=row.get("title") or "（未命名题集）",
                subtitle="", question_count=len(items),
                created_at=row.get("created_at") or "",
                author_label=row.get("author_label") or models.GUEST_LABEL,
            ))
        return out

    def _official_sop_items(self) -> List[Dict[str, Any]]:
        bindings = {b["ref_id"]: b["node_id"] for b in self.store.list_bindings(models.SCOPE_SOP)}
        if not bindings:
            return []
        out: List[Dict[str, Any]] = []
        for brief in self.sop_src.list_briefs():
            node_id = bindings.get(brief["sop_id"])
            if not node_id:
                continue
            out.append(models.tree_item(
                origin="official", ref_id=brief["sop_id"], node_id=node_id,
                kind=models.BIND_KIND_SOP, title=brief["title"],
                subtitle=brief.get("description", ""),
            ))
        return out

    # ---- 题集只读代理 ----

    def dataset_card(self, ref_id: str, origin: str) -> Optional[Dict[str, Any]]:
        if origin == "user":
            row = self.store.get_submission(ref_id)
            if not row or row.get("scope_id") != models.SCOPE_EVAL or row.get("kind") != models.KIND_DATASET:
                return None
            payload = row.get("payload") or {}
            items = payload.get("items") if isinstance(payload.get("items"), list) else []
            return {
                "dataset_id": ref_id,
                "title": row.get("title") or "（未命名题集）",
                "description": payload.get("description", "") or "",
                "question_count": len(items),
                "category": payload.get("domain", "") or "",
                "version": "",
                "meta": {},
                "origin": "user",
                "author_label": row.get("author_label") or models.GUEST_LABEL,
            }
        card = self.eval_src.dataset_card(ref_id)
        if card is None:
            return None
        card["origin"] = "official"
        if not self.store.is_bound(scope_id=models.SCOPE_EVAL, kind=models.BIND_KIND_DATASET, ref_id=ref_id):
            return None  # 题集存在但未公开
        return card

    def list_questions(
        self, ref_id: str, origin: str, offset: int = 0, limit: int = 50
    ) -> Tuple[List[Dict[str, Any]], int]:
        if origin == "user":
            row = self.store.get_submission(ref_id)
            if not row or row.get("scope_id") != models.SCOPE_EVAL or row.get("kind") != models.KIND_DATASET:
                return [], 0
            payload = row.get("payload") or {}
            questions = self._user_questions(row)
            page = questions[offset:offset + limit]
            return page, len(questions)
        if not self.store.is_bound(scope_id=models.SCOPE_EVAL, kind=models.BIND_KIND_DATASET, ref_id=ref_id):
            return [], 0
        rows, total = self.eval_src.list_questions(
            ref_id, offset=offset, limit=limit, show_gold=_show_gold_default(),
        )
        return [self._official_question_out(r) for r in rows], total

    @staticmethod
    def _official_question_out(row: Dict[str, Any]) -> Dict[str, Any]:
        """官方题公开投影：白名单字段重建，gold 列物理不进响应。

        SHOW_GOLD 只放行参考答案（gold 里的 answer 文本，人工确认口径的「参考答案」），
        其余七张 gold（retrieval/sql/sop/probe/rubric/numeric…）任何开关下都不出。
        """
        answer = None
        if _show_gold_default():
            gold = row.get("answer_gold")
            if isinstance(gold, dict):
                answer = gold.get("reference_answer") or gold.get("answer") or None
        tags = row.get("tags") if isinstance(row.get("tags"), list) else []
        return models.question_out(
            question_id=str(row.get("question_id") or ""),
            question=row.get("question") or "",
            intent_level=row.get("intent_level") or "L1",
            origin="official",
            answer=answer,
            tags=[str(t) for t in tags],
        )

    def _user_questions(self, dataset_submission: Dict[str, Any]) -> List[Dict[str, Any]]:
        """投稿题集内的题目（题集 payload + 该题集名下的单题投稿），统一公开投影。"""
        payload = dataset_submission.get("payload") or {}
        items = payload.get("items") if isinstance(payload.get("items"), list) else []
        out: List[Dict[str, Any]] = []
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            tags = item.get("tags") if isinstance(item.get("tags"), list) else []
            out.append(models.question_out(
                question_id=f"u{idx}-{dataset_submission['submission_id']}",
                question=str(item.get("question") or ""),
                intent_level=item.get("intent_level") if item.get("intent_level") in models.INTENT_LEVELS else "L1",
                origin="user",
                answer=item.get("answer") or None,
                tags=[str(t) for t in tags],
                created_at=dataset_submission.get("created_at") or "",
                author_label=dataset_submission.get("author_label") or models.GUEST_LABEL,
            ))
        extra_rows, _ = self.store.list_submissions(
            scope_id=models.SCOPE_EVAL, kinds=[models.KIND_QUESTION],
            parent_ref=dataset_submission["submission_id"], limit=500,
        )
        for row in extra_rows:
            q_payload = row.get("payload") or {}
            out.append(models.question_out(
                question_id=row["submission_id"],
                question=str(q_payload.get("question") or row.get("title") or ""),
                intent_level=q_payload.get("intent_level") if q_payload.get("intent_level") in models.INTENT_LEVELS else "L1",
                origin="user",
                answer=q_payload.get("answer") or None,
                created_at=row.get("created_at") or "",
                author_label=row.get("author_label") or models.GUEST_LABEL,
            ))
        return out

    # ---- SOP 只读代理 ----

    def get_sop(self, sop_id: str) -> Optional[Dict[str, Any]]:
        """仅 published + 已绑定才可见；其余一律 None（路由回 404，不区分「不存在/未公开」防探测）。

        status 在 SopSource 已复核过一次，这里再兜一道：假源/上游过滤坏掉也不放草稿进公开面。
        """
        if not self.store.is_bound(scope_id=models.SCOPE_SOP, kind=models.BIND_KIND_SOP, ref_id=sop_id):
            return None
        sop = self.sop_src.get(sop_id)
        if sop is None or sop.get("status") != "published":
            return None
        return sop

    def list_comments(self, sop_id: str) -> List[Dict[str, Any]]:
        rows, _ = self.store.list_submissions(
            scope_id=models.SCOPE_SOP, kinds=[models.KIND_SOP_COMMENT], parent_ref=sop_id, limit=500,
        )
        out: List[Dict[str, Any]] = []
        for row in rows:
            payload = row.get("payload") or {}
            out.append({
                "comment_id": row["submission_id"],
                "sop_id": sop_id,
                "step_ref": row.get("step_ref") or "",
                "comment": payload.get("comment") or "",
                "author_label": row.get("author_label") or models.GUEST_LABEL,
                "created_at": row.get("created_at") or "",
            })
        return out

    # ---- 投稿（本版只收不审：一律 received） ----

    def create_submission(
        self,
        *,
        scope: str,
        kind: str,
        payload: Dict[str, Any],
        node_id: str = "",
        parent_ref: str = "",
        step_ref: str = "",
        title: str = "",
        owner_key: str = "",
        user_id: Optional[int] = None,
        author_label: str = models.GUEST_LABEL,
    ) -> Dict[str, Any]:
        self._check_rate(owner_key)
        self._check_target(scope=scope, kind=kind, node_id=node_id, parent_ref=parent_ref, step_ref=step_ref)
        payload = self._validate_payload(kind=kind, payload=payload, title=title, parent_ref=parent_ref)
        title = (title or "").strip()[:models.MAX_TITLE] or self._default_title(kind, payload)
        row = self.store.insert_submission(
            scope_id=scope, kind=kind, payload=payload,
            node_id=node_id, parent_ref=parent_ref, step_ref=step_ref,
            title=title, author_owner_key=owner_key, author_user_id=user_id,
            author_label=author_label or models.GUEST_LABEL,
        )
        return models.submission_out(row)

    def _check_rate(self, owner_key: str) -> None:
        used = self.store.count_submissions_since(owner_key, hours=24)
        if used >= _daily_limit():
            raise SubmissionError(429, f"提交过于频繁：每 24 小时最多 {_daily_limit()} 条，请稍后再试。")

    def _check_target(
        self, *, scope: str, kind: str, node_id: str, parent_ref: str, step_ref: str
    ) -> None:
        if scope not in models.SCOPES or kind not in models.SUBMISSION_KINDS:
            raise SubmissionError(400, "scope 或 kind 不合法。")
        if kind == models.KIND_DATASET:
            if node_id and self.store.get_node(node_id) is None:
                raise SubmissionError(404, "所选分类不存在。")
        elif kind == models.KIND_QUESTION:
            if not parent_ref:
                raise SubmissionError(400, "添加题目须指明目标测试集。")
            if parent_ref.startswith("sub-"):
                target = self.store.get_submission(parent_ref)
                if not target or target.get("kind") != models.KIND_DATASET:
                    raise SubmissionError(404, "目标测试集不存在。")
            elif not self.store.is_bound(scope_id=models.SCOPE_EVAL, kind=models.BIND_KIND_DATASET, ref_id=parent_ref):
                raise SubmissionError(404, "目标测试集不存在或未公开。")
        elif kind == models.KIND_SOP_COMMENT:
            if not parent_ref:
                raise SubmissionError(400, "提意见须指明目标 SOP。")
            if self.sop_src.get(parent_ref) is None:
                raise SubmissionError(404, "目标 SOP 不存在或尚未公开。")
            if step_ref:
                steps = (self.sop_src.get(parent_ref) or {}).get("steps") or []
                step_ids = {str(s.get("id") or "") for s in steps if isinstance(s, dict)}
                if step_ref not in step_ids:
                    raise SubmissionError(404, "目标步骤不存在。")

    def _validate_payload(
        self, *, kind: str, payload: Dict[str, Any], title: str, parent_ref: str
    ) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            raise SubmissionError(400, "提交内容格式不合法。")
        import json as _json
        if len(_json.dumps(payload, ensure_ascii=False)) > models.MAX_PAYLOAD_CHARS:
            raise SubmissionError(400, "提交内容过大，请拆小一些再提。")
        if kind == models.KIND_DATASET:
            items = payload.get("items")
            if not isinstance(items, list) or not items:
                raise SubmissionError(400, "题集至少包含一道题。")
            if len(items) > models.MAX_ITEMS_PER_DATASET:
                raise SubmissionError(400, f"单个题集最多 {models.MAX_ITEMS_PER_DATASET} 题。")
            clean_items: List[Dict[str, Any]] = []
            for item in items:
                if not isinstance(item, dict) or not str(item.get("question") or "").strip():
                    raise SubmissionError(400, "每题必须包含题干文本。")
                clean_items.append({
                    "question": str(item["question"]).strip()[:models.MAX_TEXT],
                    "intent_level": item.get("intent_level") if item.get("intent_level") in models.INTENT_LEVELS else "L1",
                    "answer": str(item.get("answer") or "").strip()[:models.MAX_TEXT],
                })
            return {
                "description": str(payload.get("description") or "").strip()[:models.MAX_TEXT],
                "domain": str(payload.get("domain") or "").strip()[:60],
                "items": clean_items,
            }
        if kind == models.KIND_QUESTION:
            question = str(payload.get("question") or "").strip()
            if not question:
                raise SubmissionError(400, "题干不能为空。")
            return {
                "question": question[:models.MAX_TEXT],
                "intent_level": payload.get("intent_level") if payload.get("intent_level") in models.INTENT_LEVELS else "L1",
                "answer": str(payload.get("answer") or "").strip()[:models.MAX_TEXT],
            }
        # sop_comment
        comment = str(payload.get("comment") or "").strip()
        if not comment:
            raise SubmissionError(400, "意见内容不能为空。")
        return {"comment": comment[:models.MAX_TEXT]}

    @staticmethod
    def _default_title(kind: str, payload: Dict[str, Any]) -> str:
        if kind == models.KIND_DATASET:
            return "（网友投稿题集）"
        if kind == models.KIND_QUESTION:
            return str(payload.get("question") or "")[:40]
        return str(payload.get("comment") or "")[:40]
