"""L4 合成管线：问题 → 实体链接 → 候选路径 → 确定性排序 → 生成器出 SOP。

plan-sop-l4-synth Task 3。本模块只经 docs-api HTTP 取数（boundary 测试管辖
sop-api 目录），LLM 生成走 sop_core 生成器（Task 2 公共入口）。
失败语义：任何一环缺料抛 SynthUnavailable → 端点层转 412，运行时回落 complex 兜底。
"""
import logging
import re
import uuid
from typing import Any, Dict, List, Optional

import requests

from sop_core.sop_loader import normalize_step_dict
from sop_core.sop_path_generator import SopPathGenerator
from sop_core.sop_validator import validate_sop_data

logger = logging.getLogger(__name__)

_MAX_ENTITIES = 8
_MAX_DEPTH = 8
_KEYWORD_MAX = 6


class SynthUnavailable(Exception):
    """图谱侧缺料（无实体/无路径），调用方应转 412。"""


def extract_keywords(query: str) -> List[str]:
    """极简分词：CJK 2-6 字滑窗 + ASCII 词，截 6 个（v1 确定性，无分词依赖）。"""
    text = str(query or "")
    tokens: List[str] = []
    for ascii_word in re.findall(r"[A-Za-z][A-Za-z0-9_]{1,}", text):
        tokens.append(ascii_word.lower())
    for cjk in re.findall(r"[\u4e00-\u9fff]{2,8}", text):
        for width in (4, 3, 2):
            added = False
            for i in range(0, max(len(cjk) - width + 1, 0)):
                tokens.append(cjk[i:i + width])
                added = True
            if added:  # 本宽度档有产出才停；勿判 tokens 全量（ASCII 词已先入列）
                break
    seen, out = set(), []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            out.append(t)
        if len(out) >= _KEYWORD_MAX:
            break
    return out


def _http(session: requests.Session, base_url: str, path: str, params: dict) -> Any:
    resp = session.get(f"{base_url.rstrip('/')}{path}", params=params, timeout=20.0)
    resp.raise_for_status()
    return resp.json()


def search_entities(session: requests.Session, base_url: str, keywords: List[str],
                    library_id: str = "") -> List[Dict[str, Any]]:
    """逐关键词搜实体，按 entity_id 去重合并，ACTION 层排前。"""
    merged: Dict[str, Dict[str, Any]] = {}
    for kw in keywords:
        try:
            params: Dict[str, Any] = {"q": kw}
            if library_id:
                params["library_id"] = library_id
            for e in _http(session, base_url, "/api/graph/entities/search", params):
                merged.setdefault(e["entity_id"], e)
        except Exception as exc:  # noqa: BLE001
            logger.warning("实体搜索失败（q=%s）: %s", kw, exc)
    entities = list(merged.values())
    entities.sort(key=lambda e: 0 if e.get("layer") == "action" else 1)
    return entities[:_MAX_ENTITIES]


def fetch_relations(session: requests.Session, base_url: str, entity_id: str) -> List[Dict[str, Any]]:
    try:
        return _http(session, base_url, f"/api/graph/relations/{entity_id}", {})
    except Exception as exc:  # noqa: BLE001
        logger.warning("关系拉取失败（%s）: %s", entity_id, exc)
        return []


def build_candidate_paths(entities: List[Dict[str, Any]], relations_by_id: Dict[str, List[Dict[str, Any]]],
                          library_id: str = "", doc_id: str = "") -> List[List[str]]:
    """ACTION 锚定的入向链（与 generate_sops_from_doc 同语义），缺 ACTION 时退单实体。"""
    by_id = {e["entity_id"]: e for e in entities}
    paths: List[List[str]] = []
    seen = set()
    anchors = [e for e in entities if e.get("layer") == "action"] or entities
    for anchor in anchors:
        path = [anchor["name"]]
        current = anchor["entity_id"]
        for _ in range(_MAX_DEPTH):
            rels = [r for r in relations_by_id.get(current, [])
                    if (not library_id or r.get("library_id") == library_id)
                    and (not doc_id or r.get("doc_id") == doc_id)]
            if not rels:
                break
            prev = by_id.get(rels[0].get("source_id", ""))
            if not prev or prev["name"] in path:
                break
            path.insert(0, prev["name"])
            current = prev["entity_id"]
        key = "→".join(path)
        if key not in seen and len(path) >= 1:
            seen.add(key)
            paths.append(path)
    return paths


def rank_paths(paths: List[List[str]], entities: List[Dict[str, Any]]) -> List[List[str]]:
    """确定性排序：含 ACTION 的路径优先（合成时 anchors 已按 action 排前，保序即可），其次长度。"""
    layer_by_name = {e["name"]: e.get("layer") for e in entities}

    def score(p: List[str]) -> tuple:
        return (any(layer_by_name.get(n) == "action" for n in p), len(p))

    return sorted(paths, key=score, reverse=True)


def _llm_generate(generator: SopPathGenerator, title: str, steps: List[str],
                  library_id: str, doc_id: str) -> Optional[Dict[str, Any]]:
    """LLM 生成（Task 2 公共入口）；llm_enabled=False 或失败由调用方兜底骨架。"""
    return generator.generate_sop_from_steps(title, steps, "", library_id, doc_id)


def synthesize_sop(query: str, library_id: str, doc_ids: List[str], *,
                   session: Optional[requests.Session] = None, base_url: str = "",
                   llm_enabled: bool = True, config_name: Optional[str] = None) -> Dict[str, Any]:
    """问题 → 临时 SOP。返回 {"sop": <已归一化的 Step 契约形态 dict>, "path": [...]}。"""
    session = session or requests.Session()
    session.trust_env = False  # 绕系统代理（localhost 旧坑，同 eec9438）
    keywords = extract_keywords(query)
    if not keywords:
        raise SynthUnavailable("查询无可提取关键词")
    entities = search_entities(session, base_url, keywords, library_id=library_id)
    if not entities:
        raise SynthUnavailable("实体搜索无命中")
    relations_by_id = {e["entity_id"]: fetch_relations(session, base_url, e["entity_id"]) for e in entities}
    paths = rank_paths(build_candidate_paths(entities, relations_by_id, library_id=library_id), entities)
    if not paths:
        raise SynthUnavailable("未构建出候选路径")
    path = paths[0]
    entities_map = {e["name"]: e["layer"] for e in entities}
    generator = SopPathGenerator(store=None, config_name=config_name)
    if llm_enabled:
        sop = _llm_generate(generator, path[-1], path, library_id, doc_ids[0] if doc_ids else "")
    else:
        sop = None
    if not sop or not sop.get("steps"):
        sop = generator.generate_sop_skeleton(
            sop_id=uuid.uuid4().hex[:8], title=path[-1], path_entities=path,
            entities=entities_map, library_id=library_id,
            doc_id=doc_ids[0] if doc_ids else "",
        )
    sop.setdefault("id", uuid.uuid4().hex[:8])
    # 先归一化再校验：裸 skeleton / execution 嵌套形态缺顶层 tool（Step.tool 契约必填），
    # 直接 validate 必挂；校验不过按缺料处理（端点转 412 → 运行时回落 complex 兜底）。
    sop["steps"] = [normalize_step_dict(s) for s in (sop.get("steps") or [])]
    problems = validate_sop_data(sop)
    if problems:
        raise SynthUnavailable("合成 SOP 校验未过: " + "; ".join(problems))
    return {"sop": sop, "path": path}
