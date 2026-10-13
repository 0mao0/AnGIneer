# L4 车道（阶段 3）细化施工单

> **For agentic workers:** 本单是主方案 `docs/plan-sop-api-l4.md` §6.3 的 Task 级展开。前置：阶段 0-2 已落地（见主方案执行状态节）。步骤用 checkbox（`- [ ]`）跟踪，按任务顺序执行，每任务独立 commit。

> **评审修订（2026-10-12）**：相对初稿已修——①Task 3 出管线前先 `_normalize_step_dict` 再校验（裸 skeleton/execution 嵌套形态缺顶层 `tool`，撞 Step 契约必填，直接校验必挂）；②`extract_keywords` 滑窗 break 条件改「本档有产出」（原写法把 ASCII 词算进 tokens，混合查询丢短 CJK 段）；③Task 5 `summary` 先提升为变量（现状是 return 内联 f-string，直接用会 NameError）；④Task 5 测试改用既有 FakeClassifier/FakeRunner 造具（原 patch 目标 `agent_tools.SopRunner` 是 handler 内 lazy import，模块命名空间无此属性）；⑤docs-api 前缀是单数 `/api/graph`，关系端点补 library_id/doc_id 序列化（否则真实链路静默空转且单测全 mock 发现不了）；⑥crystallize 补 ValueError→422；⑦各测试补缺失 import。

**目标**：route 未命中时，聊天运行时经 sop-api 现场合成一条临时 SOP 并用 SopRunner 执行；成功且全步骤无失败时异步结晶为 draft 进人工审核流。开关默认关，关=与现状逐键一致。

**架构**：回调注入——angineer-core 的 `sop_execute` 适配器只增加 `synth_callback`/`crystallize_callback` 两个参数位（库不做 sop-api HTTP）；HTTP 实现住在 aichat-api 装配层（`sop_api_client.py`），开关 `ANGINEER_SOP_L4_SYNTH=1` 时才注入。合成管线（搜实体→建路径→排序→骨架/LLM 细化→校验）在 sop-api `path_selector.py`。

**技术栈**：既有件复用为主——`SopPathGenerator`（骨架+LLM 生成）、`validate_sop_data`/`save_generated_sop`（闸+落盘）、docs-api `/entities/search`、`/relations/{id}`（既有只读端点）。

---

## §0 施工者须知（现状锚点）

- 挂点：`services/angineer-core/src/angineer_core/agent_tools.py` `SopRunnerAdapter.sop_execute` handler 内，route-miss 分支现状：

```python
selected_sop = route_result.sop
if selected_sop is None or route_result.confidence < SOP_ROUTE_CONFIDENCE_THRESHOLD:
    return {
        "error": "未匹配到合适的 SOP",
        "reason": route_result.reason or "SOP 路由未命中",
        "confidence": route_result.confidence,
    }
```

- 调用链（chat 流）：`aichat-api/main.py` `make_policy_config_factory(...)`（chat_agent.py:83，每问题一次）→ `agent_policy.build_attempts(...)`（:123，**run_policy_query/evals/nightly 也走这里，本单不传 l4 参数即不接 L4**）→ `agent_configs.build_complex_config`（:686，:751 构造 sop_execute）。
- UI 结论：现网聊天 UI 只显示 `matched_sop` 名称（`packages/aichat-ui/src/types/chat.ts:211`），无 sop 步骤卡片——L4 来源标记落服务端字段（`l4_synth`），**前端零改动**。
- docs-api `/entities/search` 现返回 `{entity_id, name, layer, status}`，**未暴露 library_id 过滤**（Task 1 补，防串库）。
- docs-api 图谱路由前缀是 **`/api/graph`（单数）**（docs-api main.py:129）——本单全部 URL 按单数写；`/api/graphs` 是文档漂移（sop-api README:9、主方案 §6.3 curl 同款，Task 1 顺手修）。
- docs-api `/relations/{entity_id}` 现返回 8 字段、**不含 library_id/doc_id**（底层 GraphRelation 有这两列，只是没序列化；Task 1 补——不补则 Task 3 的 library_id 过滤把关系全滤光、入向链恒为单节点，且单测 mock 带了这两字段恰好掩盖）。
- 关系端点返回键名是 `type`/`evidence`/`clause`（端点改名），不是 dataclass 的 `relation_type`/`evidence_text`/`source_clause`。

## §1 前置核查（动手前跑一遍）

- [x] `pytest tests/unit/test_unit_sop_boundary.py -q` 绿（边界不回退）
- [x] `git log --oneline -1` 确认在 4e5546df 之后
- [x] docs-api 可启动且 `/api/graph/entities/search?q=码头` 返回 200（本地或容器任一）

## Task 1: docs-api 实体搜索补 library_id 过滤 + 关系端点补 library_id/doc_id（防串库）

**Files:**
- Modify: `services/docs-api/graph_routes.py:161`（`search_entities` 端点）与 :248（`get_entity_relations` 端点）
- Modify: `services/sop-api/README.md:9`、`docs/plan-sop-api-l4.md`（`/api/graphs` → `/api/graph` 漂移修正）

- [x] **Step 1 改端点**（library_id 可选，向后兼容；store `GraphStore.search_entities` 已支持 `library_id` 形参——graph_store.py:538，store 层零改动，注意关键字传参勿按位置撞 `limit`）：

```python
@graph_router.get("/entities/search")
async def search_entities(q: str, library_id: Optional[str] = None):
    store = _get_store()
    results = store.search_entities(
        q, status=EntityStatus.APPROVED,
        library_id=library_id or None,
    )
    return [
        {"entity_id": e.entity_id, "name": e.name, "layer": e.layer.value, "status": e.status.value}
        for e in results
    ]
```

  同一文件 `get_entity_relations` 的返回 dict 追加两字段（底层 dataclass 有列，只是没序列化；`/sop-generation-bundle` 的 relations 序列化已带这两字段，可对照）：

```python
            "conflict_note": r.conflict_note,
            "library_id": r.library_id,
            "doc_id": r.doc_id,
```

- [x] **Step 2 验证**：`curl "127.0.0.1:8790/api/graph/entities/search?q=码头"` 与 `...&library_id=<某库>` 都 200（后者结果 ⊆ 前者）；`curl "127.0.0.1:8790/api/graph/relations/<某实体id>"` 返回含 library_id/doc_id
- [x] **Step 3 修文档漂移**：sop-api README 与主方案 curl 示例的 `/api/graphs` 改 `/api/graph`
- [ ] **Step 4 Commit**: `feat(docs-api): 实体搜索补 library_id 过滤 + 关系端点补 library_id/doc_id（L4 合成防串库）`

## Task 2: sop-core 生成器公共包装（供 sop-api 调 LLM 生成，不再碰私有方法）

**Files:**
- Modify: `services/sop-core/src/sop_core/sop_path_generator.py`（`SopPathGenerator` 加公共方法）
- Test: `services/sop-core/tests/test_path_generator_llm.py`（新建）

- [x] **Step 1 写失败测试**：

```python
"""SopPathGenerator.generate_sop_from_steps 公共包装测试。"""
import sys, os, unittest
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../angineer-core/src")))

from unittest.mock import patch, MagicMock
from sop_core.sop_path_generator import SopPathGenerator


class TestGenerateSopFromSteps(unittest.TestCase):
    def test_llm_success_returns_parsed_sop(self):
        gen = SopPathGenerator(store=None)
        llm_json = {
            "name_zh": "测试 SOP", "description": "d",
            "steps": [{"id": "step_1", "name": "s", "description": "x",
                       "execution": {"tool": "calculator", "inputs": {"a": "x"}, "outputs": {"r": "y"}},
                       "next_step_id": None}],
            "blackboard": {"required": ["a"], "outputs": ["r"]},
        }
        with patch("ai_inference.llm_client.chat_result_guarded") as mock_chat, \
             patch("ai_inference.llm_client.LLMClient", return_value=MagicMock()):
            mock_chat.return_value = MagicMock(text=__import__("json").dumps(llm_json))
            sop = gen.generate_sop_from_steps("测试框架", ["s"], "第3.2条", "lib", "doc")
        self.assertEqual(sop["name_zh"], "测试 SOP")
        self.assertEqual(sop["steps"][0]["execution"]["tool"], "calculator")

    def test_llm_failure_falls_back_to_skeleton(self):
        gen = SopPathGenerator(store=None)
        with patch("ai_inference.llm_client.chat_result_guarded", side_effect=RuntimeError("llm down")):
            sop = gen.generate_sop_from_steps("测试框架", ["查吃水", "算水深"], "", "", "")
        self.assertIn("steps", sop)
        self.assertTrue(len(sop["steps"]) >= 2)
```

- [x] **Step 2 跑测试确认失败**：`pytest services/sop-core/tests/test_path_generator_llm.py -q` → FAIL（无 generate_sop_from_steps 属性）
- [x] **Step 3 实现**——在 `SopPathGenerator` 类内、`_generate_sop_via_llm` 之后加：

```python
    def generate_sop_from_steps(
        self,
        framework_name: str,
        fw_steps: List[str],
        source_section: str = "",
        library_id: str = "",
        doc_id: str = "",
    ) -> Dict[str, Any]:
        """公共入口：按框架步骤序生成完整 SOP（LLM 优先，失败回退骨架）。

        L4 合成车道（plan-sop-l4-synth Task 2）与 generate_sops_from_doc 共用；
        返回 steps 为 execution 嵌套形态，交由调用方（sop-api）归一化为 Step 契约。
        """
        llm_sop = self._generate_sop_via_llm(
            framework_name=framework_name,
            fw_steps=fw_steps,
            source_section=source_section,
            library_id=library_id,
            doc_id=doc_id,
        )
        if llm_sop and llm_sop.get("steps"):
            llm_sop["id"] = llm_sop.get("id") or framework_name
            llm_sop.setdefault("library_id", library_id)
            llm_sop.setdefault("doc_id", doc_id)
            return llm_sop
        entities_map = {name: LAYER_CONCEPT for name in fw_steps}
        return self.generate_sop_skeleton(
            sop_id=framework_name,
            title=framework_name,
            path_entities=fw_steps,
            entities=entities_map,
            source_clause=source_section,
            library_id=library_id,
            doc_id=doc_id,
        )
```

- [x] **Step 4 跑测试确认通过**：`pytest services/sop-core/tests/test_path_generator_llm.py tests/knowledge_graph/test_sop_path_generator.py -q` → 全 PASS
- [x] **Step 5 Commit**: `feat(sop-core): 生成器公共入口 generate_sop_from_steps（LLM 优先骨架兜底）`

## Task 3: sop-api path_selector（搜实体→建路径→排序→合成）

**Files:**
- Create: `services/sop-api/path_selector.py`
- Test: `tests/unit/test_unit_sop_path_selector.py`

- [x] **Step 1 写失败测试**（mock docs-api HTTP，LLM 走 Task 2 的兜底路径即不需要 mock LLM——用 RuntimeError 触发骨架兜底，保证测试确定性）：

```python
"""path_selector 合成管线单元测试（docs-api HTTP 全 mock，LLM 断网走骨架兜底）。"""
import os, sys, unittest
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/sop-api")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/sop-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))

from unittest.mock import MagicMock, patch
from path_selector import SynthUnavailable, extract_keywords, build_candidate_paths, synthesize_sop


def _resp(payload):
    r = MagicMock(); r.json.return_value = payload; r.raise_for_status.return_value = None; return r


class TestExtractKeywords(unittest.TestCase):
    def test_cjk_and_ascii_tokens(self):
        kw = extract_keywords("杂货船DWT40000的设计船型满载吃水怎么算？")
        self.assertIn("杂货船", "".join(kw))
        self.assertTrue(len(kw) <= 6)

    def test_empty_query_raises_later(self):
        self.assertEqual(extract_keywords("？！。 "), [])


class TestBuildCandidatePaths(unittest.TestCase):
    def test_action_anchored_incoming_chain(self):
        entities = [
            {"entity_id": "e1", "name": "设计吃水", "layer": "action"},
            {"entity_id": "e2", "name": "吨级", "layer": "concept"},
        ]
        rels = {"e1": [{"relation_id": "r1", "source_id": "e2", "target_id": "e1",
                        "library_id": "lib", "doc_id": "doc"}]}
        paths = build_candidate_paths(entities, rels, library_id="lib", doc_id="doc")
        self.assertTrue(any(p == ["吨级", "设计吃水"] for p in paths))


class TestSynthesizeSop(unittest.TestCase):
    def test_no_candidates_raises_unavailable(self):
        session = MagicMock()
        session.get.return_value = _resp([])
        with patch("path_selector.extract_keywords", return_value=["吃水"]):
            with self.assertRaises(SynthUnavailable):
                synthesize_sop("随便", "lib", [], session=session, base_url="http://x", llm_enabled=False)

    def test_success_returns_sop_dict(self):
        session = MagicMock()
        # 实际只 2 次 GET：关键词搜索 + 锚点 e1 的关系；e2 不在实体集内，入向链止于锚点
        session.get.side_effect = [
            _resp([{"entity_id": "e1", "name": "设计吃水", "layer": "action", "status": "approved"}]),
            _resp([{"relation_id": "r1", "source_id": "e2", "target_id": "e1",
                    "library_id": "lib", "doc_id": "doc"}]),
        ]
        with patch("path_selector.extract_keywords", return_value=["吃水"]), \
             patch("path_selector._llm_generate", return_value=None):  # 断网→骨架兜底
            result = synthesize_sop("杂货船设计吃水", "lib", [], session=session, base_url="http://x", llm_enabled=True)
        self.assertIn("sop", result)
        self.assertTrue(result["sop"]["steps"])
```

- [x] **Step 2 跑测试确认失败**（模块不存在）
- [x] **Step 3 实现** `services/sop-api/path_selector.py`：

```python
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

from sop_core.sop_loader import _normalize_step_dict
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
    sop["steps"] = [_normalize_step_dict(s) for s in (sop.get("steps") or [])]
    problems = validate_sop_data(sop)
    if problems:
        raise SynthUnavailable("合成 SOP 校验未过: " + "; ".join(problems))
    return {"sop": sop, "path": path}
```

- [x] **Step 4 跑测试确认通过**：`pytest tests/unit/test_unit_sop_path_selector.py -q` → PASS
- [x] **Step 5 Commit**: `feat(sop-api): L4 合成管线 path_selector（搜实体→ACTION锚定路径→骨架/LLM 兜底→校验）`

## Task 4: sop-api synthesize / crystallize 端点

**Files:**
- Modify: `services/sop-api/sop_routes.py`（两个端点 + 请求模型；仍写在 `/{sop_id}` 之前保持 `/full` 同款书写纪律——实际无 POST `/{sop_id}` 路由，POST 与 GET 不竞争，此处是防御性排序）
- Test: `tests/unit/test_unit_sop_synth_endpoints.py`

- [ ] **Step 1 写失败测试**（TestClient + mock path_selector 与 loader）：

```python
"""synthesize/crystallize 端点测试。"""
import os, sys, json, unittest
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/sop-api")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/sop-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))

from unittest.mock import patch
from fastapi.testclient import TestClient
import main
from path_selector import SynthUnavailable

client = TestClient(main.app)

_SOP = {
    "id": "synthtest1", "name_zh": "合成测试", "description": "d",
    "steps": [{"id": "s1", "name": "s", "description": {"content": "x", "citations": []},
               "tool": "auto", "inputs": {}, "outputs": {"result": "result"}}],
    "blackboard": {"required": [], "outputs": ["result"], "all": ["result"]},
}


class TestSynthesizeEndpoint(unittest.TestCase):
    def test_200_shape(self):
        # 端点函数内 from path_selector import ...（lazy），patch 必须打 path_selector 命名空间
        with patch("path_selector.synthesize_sop", return_value={"sop": _SOP, "path": ["s"]}):
            r = client.post("/api/sops/synthesize", json={"query": "测试", "library_id": "lib"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["sop"]["steps"][0]["tool"], "auto")  # 已归一化

    def test_412_when_unavailable(self):
        with patch("path_selector.synthesize_sop", side_effect=SynthUnavailable("无实体")):
            r = client.post("/api/sops/synthesize", json={"query": "测试"})
        self.assertEqual(r.status_code, 412)
        self.assertEqual(r.json()["detail"]["error"], "no_path")


class TestCrystallizeEndpoint(unittest.TestCase):
    def test_saves_draft(self):
        with patch("sop_routes._sop_loader.save_generated_sop", return_value="synthtest1") as mock_save:
            r = client.post("/api/sops/crystallize",
                            json={"sop": _SOP, "source_query": "测试问题", "review_note": "自动结晶"})
        self.assertEqual(r.status_code, 200)
        payload = mock_save.call_args.args[1]
        self.assertEqual(payload["status"], "draft")
        self.assertEqual(payload["source"]["kind"], "l4_synth")
        self.assertEqual(payload["review"]["note"], "自动结晶")
```

- [ ] **Step 2 跑测试确认失败**
- [ ] **Step 3 实现**——`sop_routes.py` 顶部请求模型区加：

```python
class SopSynthesizeRequest(BaseModel):
    """L4 现场合成请求。"""
    query: str = Field(..., min_length=1)
    library_id: str = ""
    doc_ids: List[str] = Field(default_factory=list)
    llm_enabled: bool = True


class SopCrystallizeRequest(BaseModel):
    """合成 SOP 结晶为 draft。"""
    sop: Dict[str, Any]
    source_query: str = ""
    review_note: str = ""
```

`/full` 端点之后（仍在 `/{sop_id}` 之前）加：

```python
@sop_router.post("/synthesize")
def synthesize_sop_endpoint(req: SopSynthesizeRequest):
    """L4：问题 → 临时 SOP（不落盘）。412=图谱缺料回落运行时兜底。"""
    from path_selector import SynthUnavailable, synthesize_sop
    from docs_graph_client import _default_docs_api_url
    session = requests.Session()
    session.trust_env = False
    try:
        result = synthesize_sop(
            req.query, req.library_id, req.doc_ids,
            session=session, base_url=_default_docs_api_url(),
            llm_enabled=req.llm_enabled,
        )
    except SynthUnavailable as exc:
        raise HTTPException(status_code=412, detail={"error": "no_path", "reason": str(exc)})
    sop = result["sop"]
    # 归一化为 Step 契约形态（Task 3 出管线前已归一化，此处幂等兜底；执行端直接 Step(**s) 构造，不经 loader）
    from sop_core.sop_loader import _normalize_step_dict
    sop["steps"] = [_normalize_step_dict(s) for s in (sop.get("steps") or [])]
    problems = validate_sop_data(sop)
    if problems:
        raise HTTPException(status_code=422, detail={"error": "invalid_sop", "problems": problems})
    return {"sop": sop, "path": result.get("path", [])}


@sop_router.post("/crystallize")
def crystallize_sop_endpoint(req: SopCrystallizeRequest):
    """L4：合成 SOP 落盘为 draft（进人工审核流）。id 冲突自动换新 id。"""
    import uuid as _uuid
    sop = dict(req.sop)
    problems = validate_sop_data(sop)
    if problems:
        raise HTTPException(status_code=422, detail={"error": "invalid_sop", "problems": problems})
    sop["status"] = "draft"
    sop["source"] = {"kind": "l4_synth", "source_query": req.source_query[:200]}
    sop["review"] = {"note": req.review_note or "L4 自动结晶，待人工审核",
                     "at": datetime.now().astimezone().isoformat(timespec="seconds")}
    for attempt in range(3):
        sop_id = sop.get("id") or _uuid.uuid4().hex[:8]
        try:
            _sop_loader.save_generated_sop(sop_id, sop, overwrite=False)
            return {"status": "success", "id": sop_id, "sop_status": "draft"}
        except FileExistsError:
            sop["id"] = _uuid.uuid4().hex[:8]
        except ValueError as exc:  # save_generated_sop 落盘前还有第二道校验闸（sop_loader.py:362），勿冒成 500
            raise HTTPException(status_code=422, detail={"error": "invalid_sop", "problems": [str(exc)]})
    raise HTTPException(status_code=500, detail="crystallize 落盘重试耗尽")
```

  注意：`sop_routes.py` 顶部需 `import requests`（现未引则补）；`synthesize_sop` 与 `SynthUnavailable` 在端点函数内 import（同文件既有 lazy 风格）。
- [ ] **Step 4 跑测试确认通过**：`pytest tests/unit/test_unit_sop_synth_endpoints.py -q` → PASS
- [ ] **Step 5 Commit**: `feat(sop-api): L4 synthesize/crystallize 端点（412 缺料语义 + draft 结晶进审核流）`

## Task 5: angineer-core 适配器回调位（synth_callback / crystallize_callback）

**Files:**
- Modify: `services/angineer-core/src/angineer_core/agent_tools.py`（`SopRunnerAdapter.sop_execute`）
- Test: `tests/angineer-core/test_sop_runner_adapter.py`（追加用例）

- [ ] **Step 1 写失败测试**（追加到既有文件，沿用其 `make_sop`/`RouteResult` 造具）：

```python
class L4SynthTests(unittest.TestCase):
    """L4 回调注入：None=与现状逐键一致；注入=合成执行+结晶。"""

    def _miss_tool(self, **kw):
        miss = RouteResult(sop=None, args={}, reason="不属于任何已知 SOP",
                           confidence=0.2, candidates=[])
        return SopRunnerAdapter.sop_execute(
            sops=[make_sop(status="published")],
            classifier=FakeClassifier(miss),  # 确定性 route-miss，勿靠真 IntentClassifier 碰运气
            runner=FakeRunner(),              # 真 _build_sop_trace 是鸭子型 staticmethod，吃其 memory.history
            **kw,
        )

    def test_no_callback_returns_legacy_error(self):
        result = self._miss_tool().handler(sop_query="不相关的问题")
        self.assertEqual(result["error"], "未匹配到合适的 SOP")
        self.assertNotIn("l4_synth", result)

    def test_synth_success_runs_and_marks_l4(self):
        synth_sop = make_sop(sop_id="l4-synth-test", status="draft")
        calls = []

        def synth(query):
            return {"sop": json.loads(synth_sop.model_dump_json())}

        def crystallize(sop, source_query, summary):
            calls.append((sop, source_query, summary))

        result = self._miss_tool(synth_callback=synth, crystallize_callback=crystallize).handler(
            sop_query="不相关的问题"
        )
        self.assertTrue(result["l4_synth"])
        self.assertEqual(result["sop_id"], "l4-synth-test")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], "不相关的问题")

    def test_synth_none_returns_legacy_error(self):
        result = self._miss_tool(synth_callback=lambda q: None).handler(sop_query="不相关的问题")
        self.assertEqual(result["error"], "未匹配到合适的 SOP")
        self.assertTrue(result["l4_synth_attempted"])
```

  （造具沿用文件既有 `FakeClassifier`/`FakeRunner`/`RouteResult`/`make_sop`。**不要** `patch("angineer_core.agent_tools.SopRunner")`——SopRunner 是 handler 内 lazy import（agent_tools.py:1316），模块命名空间无此属性，patch 启动即 AttributeError。该文件头未 import json，需补。）
- [ ] **Step 2 跑测试确认失败**：`pytest tests/angineer-core/test_sop_runner_adapter.py -q` → 新用例 FAIL（unexpected keyword）
- [ ] **Step 3 实现**——`sop_execute` 签名加 `synth_callback: Optional[Callable[[str], Any]] = None, crystallize_callback: Optional[Callable[[Dict[str, Any], str, str], None]] = None`；handler 的 route-miss 分支替换为：

```python
            selected_sop = route_result.sop
            l4_synth = False
            if selected_sop is None or route_result.confidence < SOP_ROUTE_CONFIDENCE_THRESHOLD:
                legacy_error = {
                    "error": "未匹配到合适的 SOP",
                    "reason": route_result.reason or "SOP 路由未命中",
                    "confidence": route_result.confidence,
                }
                if synth_callback is None:  # 开关关：早退，与现状逐键一致
                    return legacy_error
                synth = synth_callback(query)  # → {"sop": <契约形态 dict>} | None
                if not isinstance(synth, dict) or not synth.get("sop"):
                    return {**legacy_error, "l4_synth_attempted": True}
                from angineer_core.base_contracts import SOP as SopContract
                try:
                    selected_sop = SopContract(**synth["sop"])
                except Exception as exc:  # noqa: BLE001
                    logger.warning("L4 合成 SOP 构造失败: %s", exc)
                    return {**legacy_error, "l4_synth_attempted": True, "l4_synth_error": str(exc)[:200]}
                l4_synth = True
```

  执行与返回段：`success_steps/failed_steps` 计算之后、原 `return` 之前——**先把现状 return 内联的 summary f-string（agent_tools.py:1350-1353）提升为变量**（不提升则结晶钩子与返回体引用 `summary` 均 NameError），再加结晶钩子，return dict 改引用该变量并追加 `l4_synth`：

```python
            summary = (
                f"命中 SOP {selected_sop.id}，执行 {len(sop_trace)} 步，"
                f"成功 {success_steps} 步，失败 {failed_steps} 步"
            )
            if l4_synth and crystallize_callback is not None and failed_steps == 0 and success_steps > 0:
                try:
                    crystallize_callback(synth["sop"], query, summary)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("L4 crystallize 回调失败（不阻断返回）: %s", exc)
            return {  # 原有九个字段逐键保留（summary 改引用上面变量），仅追加 l4_synth
                "sop_id": selected_sop.id,
                "sop_name": selected_sop.name_zh or selected_sop.name_en or selected_sop.id,
                "confidence": route_result.confidence,
                "summary": summary,
                "steps": [
                    {
                        "step_id": s.get("step_id"),
                        "step_name": s.get("step_name"),
                        "status": s.get("status"),
                        "outputs": s.get("outputs"),
                    }
                    for s in sop_trace
                ],
                "final_context": final_context or {},
                "sop_trace": sop_trace,
                "citations": citations,
                "route_reason": route_result.reason or "",
                "l4_synth": l4_synth,
            }
```

  （`synth["sop"]` 在 l4_synth=False 时未定义——结晶钩子被 `l4_synth and` 短路，安全。）
- [ ] **Step 4 跑测试确认通过**：`pytest tests/angineer-core/test_sop_runner_adapter.py tests/angineer-core -q` → 全 PASS
- [ ] **Step 5 Commit**: `feat(sop): sop_execute 适配器加 synth_callback/crystallize_callback 回调位（None=现状逐键一致）`

## Task 6: aichat 装配层接线（开关 + 每问题预算 + HTTP 回调实现）

**Files:**
- Modify: `services/aichat-api/sop_api_client.py`（加 `build_l4_hooks`）
- Modify: `services/angineer-core/src/angineer_core/agent_policy.py:123`（`build_attempts` 加 `l4_synth=None` 透传）
- Modify: `services/angineer-core/src/angineer_core/agent_configs.py:686`（`build_complex_config` 加 `l4_synth=None`，:751 传给 sop_execute）
- Modify: `services/aichat-api/chat_agent.py:83`（`make_policy_config_factory` 构造 hooks）
- Modify: `.env.example`（登记开关）

- [ ] **Step 1** `sop_api_client.py` 末尾加：

```python
def build_l4_hooks(client: "SopApiClient", budget: Dict[str, int]):
    """L4 回调对（synth, crystallize）；budget 由装配层按问题创建（每问题至多 1 次合成）。"""
    def synth(query: str, library_id: str = "", doc_ids: Optional[List[str]] = None):
        if budget.get("used", 0) >= 1:
            return None
        budget["used"] = budget.get("used", 0) + 1
        try:
            resp = client.session.post(
                f"{client.base_url}/api/sops/synthesize",
                json={"query": query, "library_id": library_id or "",
                      "doc_ids": list(doc_ids or []), "llm_enabled": True},
                timeout=120.0,
            )
            if resp.status_code != 200:
                logger.info("L4 synthesize 未命中（%s）: %s", resp.status_code, resp.text[:200])
                return None
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("L4 synthesize 调用失败: %s", exc)
            return None

    def crystallize(sop: Dict[str, Any], source_query: str, summary: str):
        try:
            client.session.post(
                f"{client.base_url}/api/sops/crystallize",
                json={"sop": sop, "source_query": source_query, "review_note": summary[:200]},
                timeout=15.0,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("L4 crystallize 调用失败（不阻断）: %s", exc)

    return synth, crystallize
```

- [ ] **Step 2** `agent_policy.build_attempts` 签名加 `l4_synth: Optional[Any] = None`，complex 分支 `build_complex_config(..., l4_synth=l4_synth)`（其余分支不传，L1/L2/L0 天然不接 L4）
- [ ] **Step 3** `agent_configs.build_complex_config` 签名加 `l4_synth: Optional[Any] = None`；:751 `sop_execute(...)` 调用追加：

```python
                synth_callback=l4_synth[0] if l4_synth else None,
                crystallize_callback=l4_synth[1] if l4_synth else None,
```

- [ ] **Step 4** `chat_agent.make_policy_config_factory` 的 `factory()` 内、`build_attempts(...)` 调用前加：

```python
        # L4 车道（plan-sop-l4-synth Task 6）：开关开才注入回调；预算按问题粒度
        l4_synth = None
        if os.getenv("ANGINEER_SOP_L4_SYNTH", "0") == "1" and sop_loader is not None:
            from sop_api_client import build_l4_hooks
            l4_budget = {"used": 0}
            synth, crystallize = build_l4_hooks(sop_loader, l4_budget)
            l4_synth = (lambda q: synth(q, scope.library_id, list(scope.doc_ids)), crystallize)
```

  并在 `build_attempts(...)` 调用追加 `l4_synth=l4_synth,`。**文件头补 `import os`（chat_agent.py:7-15 现状未引，勿当成已有）**。

  口径注记：主方案 §6.3 写的 synth 回调签名是 `(query, library_id, doc_ids)` 三参，本单定稿为**一元回调 + 装配层闭包绑定 scope**（语义等价）；施工 commit 后回主方案 §6.3 同步一句口径，防两文档漂移。
- [ ] **Step 5** `.env.example` 登记（`SOP_API_URL` 行（:158）后；顺手把 :158 行尾粘连的 `ANGINEER_SOP_DOMAIN_PACK` 注释拆回 :157 裸行——既有格式瑕疵）：

```
# ANGINEER_SOP_L4_SYNTH=0              # L4 车道：route 未命中时现场合成临时 SOP 并执行（默认关；=1 开；结晶 draft 进人工审核流）
```

- [ ] **Step 6 回归**：`pytest tests/angineer-core tests/unit/test_unit_sop_api_client.py -q` 全 PASS（既有用例不传 l4 → 行为不变）
- [ ] **Step 7 Commit**: `feat(sop): L4 车道装配接线——开关 ANGINEER_SOP_L4_SYNTH（默认关）+ 每问题 1 次合成预算 + HTTP 回调实现`

## Task 7: 验收（预注册）

- [ ] **单测集全绿**：`pytest tests/unit tests/angineer-core services/sop-core/tests tests/knowledge_graph/test_sop_path_generator.py -q`（分开跑，两目录同名模块不可合跑）
- [ ] **开关关一致性**：Task 5 的 `test_no_callback_returns_legacy_error` 即构造性断言
- [ ] **手测开关开**：本地 `.env` 临时 `ANGINEER_SOP_L4_SYNTH=1` + 重启 aichat → 问一道**故意海港题集覆盖不到**的复合计算题 → 观察 sop-api 日志 synthesize 调用、回答带 l4_synth 结果、`data/platform/sops/json/` 出现 draft、管理页审核流可发布
- [ ] **预注册对照（跑前写死）**：20 题海港计算题集（从既有评测题集抽），A 臂=开关关、B 臂=开；判据：①B 正确题数 ≥ A 正确题数 − 5（噪声地板内）；②B 的合成调用成功率与 412 率如实记录（能力画像，非门禁）；③无判分闸回退。结果只报不改 nightly 门禁（业主口径）
- [ ] **证据闸核查**（主方案 §6.3 遗留验证项）：确认 complex 档 `final_answer_guard(enforce_evidence=True)` 对 L4 合成执行的回答同样生效——手测开关开时给一道无证据支撑的合成题，确认答案被闸拦截而非放行
- [ ] **恢复默认关**：手测后本地 `.env` 去掉开关；生产开与不开由业主拍板

## 明确不做（本单范围外）

- path_selector 的 LLM 精排选路（v1 确定性排序；LLM 只用于步骤细化一步）
- 前端 UI 标记（现网聊天无 sop 步骤卡片，`l4_synth` 字段服务端可观测即可）
- run_policy_query / nightly 接 L4（评测读数链不接新能力，保持门禁口径稳定）
- 合成 SOP 的循环/重试语义、多候选并跑
