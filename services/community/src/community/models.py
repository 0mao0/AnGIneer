"""community 模块的常量与出参形状（单一真相源，store / service / routes 共用）。"""
from typing import Any, Dict, List, Optional

# 分类树在通用 tree_node 表里的类型标识（tree_core 按 tree_type + scope_id 双维度隔离）
TREE_TYPE = "community_node"

# 两页各自一棵树：公开测试集 / 公开 SOP
SCOPE_EVAL = "eval"
SCOPE_SOP = "sop"
SCOPES = (SCOPE_EVAL, SCOPE_SOP)

# community_meta 状态位：自动绑定的「只跑一次」marker（设计 §9.1，第一轮审核 B2）
META_AUTOBIND_DONE = "autobind_done"        # 取值 f"{META_AUTOBIND_DONE}:{scope}"

# 投稿条目种类
KIND_DATASET = "dataset"
KIND_QUESTION = "question"
KIND_SOP_COMMENT = "sop_comment"
SUBMISSION_KINDS = (KIND_DATASET, KIND_QUESTION, KIND_SOP_COMMENT)

# 绑定条目种类（官方内容挂到分类节点）
BIND_KIND_DATASET = "dataset"
BIND_KIND_SOP = "sop"

# 投稿状态机：本版只写 received。后续审核开工才产生其余三态（设计 §5 D3）。
STATUS_RECEIVED = "received"
STATUS_REVIEWED = "reviewed"
STATUS_PROMOTED = "promoted"
STATUS_REJECTED = "rejected"

# 意图等级白名单（与 evals-ui EvalIntentLevel 对齐）
INTENT_LEVELS = ("L0", "L1", "L2", "L3", "L4")

# 服务端硬校验上限：全量接收不等于无界接收（设计 §8）
MAX_TITLE = 120
MAX_TEXT = 2000
MAX_ITEMS_PER_DATASET = 200
MAX_PAYLOAD_CHARS = 256 * 1024

# 游客/登录用户显示名（登录用户出参用 display_name，游客固定此串）
GUEST_LABEL = "游客"

# 限流：应用层日限是兜底，主防线是 nginx per-IP limit_req（设计 §6 R5）
DEFAULT_DAILY_LIMIT = 50


def node_out(row: Dict[str, Any]) -> Dict[str, Any]:
    """tree_node 行 → 前端左树节点。"""
    return {
        "node_id": row["node_id"],
        "parent_id": row.get("parent_id"),
        "title": row.get("title") or "",
        "sort_order": int(row.get("sort_order") or 0),
    }


def binding_out(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "binding_id": row["binding_id"],
        "scope_id": row["scope_id"],
        "kind": row["kind"],
        "ref_id": row["ref_id"],
        "node_id": row["node_id"],
        "sort_order": int(row.get("sort_order") or 0),
    }


def submission_out(row: Dict[str, Any]) -> Dict[str, Any]:
    """投稿行 → 出参（payload 已解析成 dict）。"""
    return {
        "submission_id": row["submission_id"],
        "scope_id": row["scope_id"],
        "kind": row["kind"],
        "node_id": row.get("node_id") or "",
        "parent_ref": row.get("parent_ref") or "",
        "step_ref": row.get("step_ref") or "",
        "title": row.get("title") or "",
        "payload": row.get("payload") or {},
        "author_label": row.get("author_label") or GUEST_LABEL,
        "status": row.get("status") or STATUS_RECEIVED,
        "created_at": row.get("created_at") or "",
    }


def tree_item(
    *,
    origin: str,
    ref_id: str,
    node_id: str,
    kind: str,
    title: str,
    subtitle: str = "",
    question_count: Optional[int] = None,
    created_at: str = "",
    author_label: str = "",
) -> Dict[str, Any]:
    """左树叶子条目（官方绑定与用户投稿合一形状，前端按 origin 打徽标）。"""
    return {
        "item_id": f"{origin}:{ref_id}",
        "origin": origin,          # official | user
        "ref_id": ref_id,
        "node_id": node_id,
        "kind": kind,              # dataset | sop | question
        "title": title,
        "subtitle": subtitle,
        "question_count": question_count,
        "created_at": created_at,
        "author_label": author_label,
    }


def question_out(
    *,
    question_id: str,
    question: str,
    intent_level: str = "L1",
    origin: str = "official",
    answer: Optional[str] = None,
    tags: Optional[List[str]] = None,
    created_at: str = "",
    author_label: str = "",
) -> Dict[str, Any]:
    """题目公开投影：只出题干/等级/（可选）参考答案，八张 gold 一律不外泄（设计 §6 R2）。"""
    out: Dict[str, Any] = {
        "question_id": question_id,
        "question": question,
        "intent_level": intent_level,
        "origin": origin,
        "tags": tags or [],
    }
    if answer is not None:
        out["answer"] = answer
    if created_at:
        out["created_at"] = created_at
    if author_label:
        out["author_label"] = author_label
    return out
