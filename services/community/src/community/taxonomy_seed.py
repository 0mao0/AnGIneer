"""分类树种子 + 首次自动绑定（设计 §9）。

两类动作语义不同，别混（第一轮审核 B2）：
- 节点种子：每次启动跑，幂等**只补不覆盖**——后台改过的分类名不会被发版打回。
- 自动绑定：**只在首次**（`community_meta` 无 marker 时跑一次），跑完置位。
  此后新导入的测试集/SOP 一律默认不公开，要公开须人工
  `scripts/community_bind.py bind`。
"""
import logging
from typing import Any, Dict, List, Tuple

from community import models

logger = logging.getLogger(__name__)

# (scope 无关的) 起步树：一级专业 → 二级子专业。节点 id 全 ascii slug（§9.2）。
# 落库时统一加 `"<scope>:"` 前缀（如 `eval:dom-waterway`）：tree_node.node_id 是全局主键，
# 不带前缀则 eval 与 sop 两棵树互相顶名（第二轮施工实证）。
SEED_TAXONOMY: List[Tuple[str, str, List[Tuple[str, str]]]] = [
    # 通用置顶（业主 10-15 定）：跨专业条目（端到端评测集等）直接挂本节点，不设二级子目录。
    # 不进 AUTOBIND_KEYWORDS——通用成员名单属人工决定，一律走 community_bind.py 手工绑。
    ("dom-general", "通用", []),
    ("dom-highway", "公路", [
        ("sp-highway-subgrade", "路基路面"),
        ("sp-highway-bridge", "桥梁"),
        ("sp-highway-tunnel", "隧道"),
        ("sp-highway-safety", "交通安全设施"),
    ]),
    ("dom-waterway", "水运", [
        ("sp-waterway-channel", "航道"),
        ("sp-waterway-port", "港口"),
        ("sp-waterway-lock", "船闸"),
        ("sp-waterway-dredging", "疏浚"),
    ]),
    ("dom-municipal", "市政", [
        ("sp-municipal-road", "道路"),
        ("sp-municipal-drainage", "给排水"),
        ("sp-municipal-bridge", "桥梁"),
        ("sp-municipal-utilidor", "综合管廊"),
    ]),
    ("dom-hydraulics", "水利", [
        ("sp-hydraulics-hydrology", "水文"),
        ("sp-hydraulics-structure", "水工建筑物"),
        ("sp-hydraulics-regulation", "河道整治"),
    ]),
]

# 首次自动绑定关键词表（§9.3，顺序即优先级：命中第一个匹配节点即绑，未命中不绑）。
# 不硬编码 id——本地与生产 dataset_id/SOP id 不同，只按标题关键词。
AUTOBIND_KEYWORDS: List[Tuple[str, List[str]]] = [
    ("sp-waterway-channel", ["航道", "通航"]),
    ("sp-waterway-port", ["港口", "码头", "泊位"]),
    ("sp-waterway-dredging", ["疏浚", "挖泥", "吹填"]),
    ("sp-hydraulics-hydrology", ["水文", "潮汐", "波浪"]),
    ("sp-highway-bridge", ["桥梁"]),
    ("sp-highway-tunnel", ["隧道"]),
    ("sp-highway-subgrade", ["路基", "路面", "沥青"]),
    ("sp-municipal-road", ["市政", "道路"]),
    ("sp-municipal-drainage", ["给排水", "排水"]),
]


def full_node_id(scope: str, slug: str) -> str:
    """落库 node_id = `<scope>:<slug>`——tree_node.node_id 全局主键，裸 slug 两棵树会互相顶名。"""
    return f"{scope}:{slug}"


def seed_tree(store) -> int:
    """两 scope 各实例化一份起步树；已存在的节点原样保留。返回新建节点数。"""
    created = 0
    for scope in models.SCOPES:
        for root_idx, (root_slug, root_title, children) in enumerate(SEED_TAXONOMY):
            root_id = full_node_id(scope, root_slug)
            if store.get_node(root_id) is None:
                created += 1
            store.ensure_node(
                root_id, scope_id=scope, title=root_title, parent_id=None, sort_order=root_idx,
            )
            for child_idx, (child_slug, child_title) in enumerate(children):
                child_id = full_node_id(scope, child_slug)
                if store.get_node(child_id) is None:
                    created += 1
                store.ensure_node(
                    child_id, scope_id=scope, title=child_title,
                    parent_id=root_id, sort_order=child_idx,
                )
    if created:
        logger.info("community 分类树种子：新建 %d 个节点", created)
    return created


def _match_node(title: str) -> str:
    """命中返回裸 slug（绑定处再按 scope 加前缀），未命中返回空串（不绑）。"""
    for slug, keywords in AUTOBIND_KEYWORDS:
        if any(kw in title for kw in keywords):
            return slug
    return ""


def autobind_once(store, eval_src, sop_src) -> Dict[str, Dict[str, Any]]:
    """首次自动绑定（marker 防重跑）。返回 {scope: {bound, total, unmatched}}。

    marker 即使绑到 0 条也置位：marker 的含义是「这个决定已经人工确认跑过」，
    不是「绑到了东西」——否则空库环境下每次重启都会重跑，等哪天导入内容就
    悄悄全部自动公开（B2 想防的正是这个）。
    """
    result: Dict[str, Dict[str, Any]] = {}
    targets = (
        (models.SCOPE_EVAL, models.BIND_KIND_DATASET,
         [(b["dataset_id"], b["title"]) for b in eval_src.list_dataset_briefs()]),
        (models.SCOPE_SOP, models.BIND_KIND_SOP,
         [(b["sop_id"], b["title"]) for b in sop_src.list_briefs()]),
    )
    for scope, kind, refs in targets:
        marker = f"{models.META_AUTOBIND_DONE}:{scope}"
        if store.get_meta(marker) is not None:
            continue
        bound = 0
        unmatched: List[str] = []
        for ref_id, title in refs:
            slug = _match_node(title or "")
            if not slug:
                unmatched.append(f"{ref_id}（{title}）")
                continue
            store.bind(scope_id=scope, kind=kind, ref_id=ref_id, node_id=full_node_id(scope, slug))
            bound += 1
        store.set_meta(marker, f"bound={bound};total={len(refs)}")
        logger.info("community 首次自动绑定[%s]：bound %d / 总 %d", scope, bound, len(refs))
        if unmatched:
            logger.info("community 首次自动绑定[%s] 未命中（需人工补绑）：%s", scope, "; ".join(unmatched))
        result[scope] = {"bound": bound, "total": len(refs), "unmatched": unmatched}
    return result


def seed_all(store, eval_src, sop_src) -> Dict[str, Any]:
    """启动装配入口：先树后绑定（绑定目标节点必须先存在）。"""
    seed_tree(store)
    return {"autobind": autobind_once(store, eval_src, sop_src)}
