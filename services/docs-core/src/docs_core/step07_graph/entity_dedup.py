"""实体去重/别名归并：优先精确，其次归一化，最后模糊相似。"""

import re
from difflib import SequenceMatcher
from typing import Optional

from docs_core.step07_graph.graph_store import GraphEntity, GraphStore

_SIMILARITY_THRESHOLD = 0.92


def normalize_entity_name(name: str) -> str:
    """归一化：去空白、全角转半角、统一小写。"""
    if not name:
        return ""
    text = str(name).strip()
    text = text.replace("\u3000", " ")
    text = re.sub(r"\s+", "", text)
    for full, half in zip("（）ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ０１２３４５６７８９",
                          "()ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"):
        text = text.replace(full, half)
    return text.lower()


def find_existing_entity(store: GraphStore, name: str, library_id: str) -> Optional[GraphEntity]:
    """在 library 范围内查找可复用的已有实体（排除 rejected）。"""
    if not name or not name.strip():
        return None
    target = str(name).strip()

    exact = store.get_entity_by_name(target, library_id)
    if exact is not None and exact.status.value != "rejected":
        return exact

    norm_target = normalize_entity_name(target)
    best: Optional[GraphEntity] = None
    best_score = 0.0

    for entity in store.list_library_entities(library_id):
        if entity.status.value == "rejected":
            continue
        if entity.name == target:
            return entity
        if any(alias == target for alias in (entity.aliases or [])):
            return entity
        norm_name = normalize_entity_name(entity.name)
        if norm_name and norm_name == norm_target:
            return entity
        if any(normalize_entity_name(a) == norm_target for a in (entity.aliases or [])):
            return entity
        score = SequenceMatcher(None, norm_name, norm_target).ratio()
        if score >= _SIMILARITY_THRESHOLD and score > best_score:
            best = entity
            best_score = score

    return best
