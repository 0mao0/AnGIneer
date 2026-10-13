# SOP 模块解耦与 L4 工厂实施方案

> **For agentic workers:** 本方案分四阶段，每阶段独立可停、可单独验收。执行时按阶段推进，每阶段动手前核对本节验收标准。步骤用 checkbox（`- [ ]`）跟踪。

**目标**：SOP 从「寄生在 aichat-api 里的路由文件」变成独立的数据面服务（sop-api，含 SOP 工厂），剪断 sop-core 对 docs-core 的内部耦合，接通「问题→现场合成临时 SOP→执行→结晶回 L3」的 L4 车道，最终 sop-core 具备 PyPI 独立发包条件。

**架构**：三服务三面——aichat-api（对话面+执行）、sop-api（SOP 数据面+工厂，新）、docs-api（知识面）；跨服务只走 HTTP 契约、存储各自独占；库层保持 DAG（sop-core → angineer-core → ai-inference）。执行器 SopRunner 留在 angineer-core 不动。

**技术栈**：FastAPI（新服务复用 `docker/Dockerfile.backend`）、sop-core/angineer-core 既有库、httpx（trust_env=False，见既有修复 eec9438）、nginx 网关。

**前置已完成**：领域知识外置 domain pack + run_sop 图遍历（b68a569e，未 push）；相关评估结论见当日架构讨论。

**执行状态（2026-10-12）**：
- 阶段 0 ✅ 1dd1309f（研究员残留）+ 659161b8（meta/演示 SOP+sop_run 桩）
- 阶段 1 ✅ 4847443b（骨架）+ 963319db（平移）+ 340424fb（/full + SopApiClient + evals 转换）——**服务器部署未做**（nginx 切流/容器重建属上线步骤，待 push 授权后按 Task 1.2 顺序执行）
- 阶段 2 ✅ c044f2c0（graph_port + bundle 端点 + HttpGraphReader + pyproject 换血 + 边界测试）；实现细化偏离：图谱读取用单端点 /sop-generation-bundle 一次取全（supersede 方案里「/frameworks + 逐端点映射」的设计，enrichment 无列表端点，bundle 保持与生成器逐实体调用语义一致）；干净 venv 装包+导入链已验（--no-deps + 最小依赖）
- 阶段 3 ⏸ 待细化施工单（synth_callback 注入设计已定稿于 §6.3）
- 阶段 4 ⏸ 待用户：版本号确认 + 独立仓创建 + PyPI trusted publisher；前置漂移核查未做（angineer-core 本地 0.1.1 vs PyPI 0.1.2）

---

## 0. 需要审核人拍板的决策点

| # | 决策 | 本方案默认 | 备选 |
| --- | --- | --- | --- |
| D1 | meta SOP（raw/ 下 meta_l1~l4.md）处置 | 留档后删除（空壳+假成功陷阱，L1/L2 能力已有原生通道） | 转 disabled JSON 保留 |
| D2 | 执行面取 SOP 列表的通道 | 经 sop-api HTTP + 末次快照兜底 | 只读共享文件（违背存储独占，不推荐） |
| D3 | L4 合成开关默认值 | `ANGINEER_SOP_L4_SYNTH=0` 默认关，观察期后开 | 直接默认开 |
| D4 | sop-api 端口 | 127.0.0.1:8792 | — |

---

## 1. 现状与证据

| # | 事实 | 锚点 |
| --- | --- | --- |
| 1 | SOP 数据面（CRUD/导入/审核/审计/图谱生成，859 行）寄生在 aichat-api | `services/aichat-api/sop_routes.py` |
| 2 | aichat-api 内部直连 docs-core 读 KG sqlite（越权跨服务） | `sop_routes.py:771`（`GraphStore(KG_DB_PATH)`） |
| 3 | sop-core 库内部 import docs-core（跨模块焊死） | `sop_core/sop_path_generator.py:6-7` |
| 4 | aichat-api 内多份 SopLoader 实例靠文件快照对齐（main / evals_routes:63，迁移前还有 sop_routes:29，共三处） | `main.py:117`、`evals_routes.py:63` |
| 5 | meta SOP 空壳：raw 来源加载成单步 `sop_run`，而该工具是桩（返回字符串不执行）→ 假成功 | `engtools/CommonTool.py:94`；meta_l3 引用的 `sop_match` 工具不存在 |
| 6 | SOP 研究员后端 7ba043a8 已拆，前端孤儿残留（sopResearch.ts / SopResearchManage.vue / sop-ui research 组件 / research_meta.sqlite） | grep 零后端实现，调用即 404 |
| 7 | L3/L4 在装配层同走 complex 档（注释自认「本计划范围外」） | `angineer_core/agent_policy.py:146` |
| 8 | SOP 文件并发写无锁（丢更新风险） | `sop_routes.py` 各写端点 |
| 9 | 图谱 HTTP 面缺 frameworks-by-doc 端点（生成器需要） | `docs-api/graph_routes.py`（entities/search/relations 已有） |

## 2. 目标架构

```mermaid
graph TB
    UI[admin-web / user-web<br>路径 /api/sops、/api/chat 不变] --> NGINX[nginx 网关]
    NGINX -->|/api/chat| CHAT[aichat-api 对话面<br>agent 循环 + SopRunner 执行]
    NGINX -->|/api/sops| SOP[sop-api 数据面（新）<br>CRUD/导入/审核/审计/工厂]
    NGINX -->|/api/knowledge 等| DOCS[docs-api 知识面]
    CHAT -->|HTTP 取 published SOP 列表| SOP
    CHAT -->|HTTP 检索/查表| DOCS
    SOP -->|HTTP 图谱读（生成时）| DOCS
    subgraph 库层（进程内嵌，DAG）
      A[angineer-core<br>SopRunner/路由/黑板/领域包]
      S[sop-core 纯库<br>loader/解析/校验/生成]
      D[docs-core]
    end
    CHAT -.内嵌.-> A
    SOP -.内嵌.-> S
    DOCS -.内嵌.-> D
    S -->|契约依赖| A
```

三条铁律（服务级）：

1. 跨服务只走 HTTP 契约，禁止 import 对方内部模块；
2. 存储独占：`data/platform/sops/` 归 sop-api 单写者；KG sqlite 归 docs-api；chat.sqlite 归 aichat-api；
3. 库级依赖保持 DAG，不追求零依赖：`sop-core → angineer-core（SOP/Step 契约）→ ai-inference`，engtools 保持可选。

边界划线（谁放哪）：

| 进 sop-api | 留在 angineer-core | 留在 aichat-api |
| --- | --- | --- |
| CRUD/导入/审核/审计/统计 | SopRunner 执行器 | agent 循环、会话、历史 |
| SOP 工厂：md 解析、图谱路径生成、问题→路径合成（L4） | IntentClassifier 路由 | 赌博式预检、评测路由、nightly |
| synthesize（不落盘）/ crystallize（落 draft）两端点 | 变量黑板、domain pack 注入 | SOP 列表拉取与 L4 回调的**装配层** |
| | sop_execute 适配器（库内不做 sop-api HTTP；SOP 列表与 synth 回调均经装配层注入） | |

### 关键设计点：执行面怎么拿 SOP 列表（D2）

现状 aichat-api 直读文件。拆分后改为：aichat-api 内新增 `sop_api_client.py`，启动及 TTL 过期时 `GET /api/sops/full?status=published` 拉全量（含 steps/blackboard），进程内缓存；**sop-api 不可达时降级用末次成功快照**（比现状更稳：现状文件坏了直接挂）。TTL 复用 `ANGINEER_SOP_CACHE_TTL`（默认 300s）。新建库立即可见性问题随之消失（不必重启 aichat，等 TTL 或 sop-api 落盘失效通知）。

---

## 3. 阶段 0：清理前置（0.5 天）

### Task 0.1 清除 SOP 研究员残留

**Files:**
- Delete: `apps/admin-web/src/api/sopResearch.ts`
- Delete: `apps/admin-web/src/views/SopResearchManage.vue`
- Delete: `packages/sop-ui/src/components/research/`（5 个组件）
- Delete: `packages/sop-ui/src/types/sopResearch.ts`
- Delete: `data/platform/sops/research_meta.sqlite`

- [ ] grep 确认以上文件无被引用（router/index.ts 已确认不引用 SopResearchManage）
- [ ] 检查 `packages/sop-ui/src/index.ts`、`components/index.ts`、`types/index.ts` 是否 export research 内容，有则同步删除
- [ ] 全量 typecheck（admin-web + sop-ui）：`pnpm -r typecheck`，预期 PASS
- [ ] 删除上述文件 + `data/platform/sops/research_meta.sqlite`
- [ ] Commit: `chore(sop): 清除 SOP 研究员前端与数据残留（后端已随 7ba043a8 移除）`

### Task 0.2 处置 meta SOP 空壳（D1）

**Files:**
- Archive: `docs/archive/meta-sop-md-2026-10/`（md 原文留档）
- Delete: `data/platform/sops/raw/meta_l1_semantic_retrieval.md`、`meta_l2_clause_lookup.md`、`meta_l3_standard_calc.md`、`meta_l4_dynamic_orchestration.md`
- Delete（英文演示 SOP 一并处置，标准统一）: `data/platform/sops/raw/code_review.md`、`math_sop.md`、`market_research.md` 及 `json/market_research.json`
  - 事实备注：market_research **不是 raw-only**（有 json、5 步，评审意见此处不准），但同为与产品语料无关的英文演示 SOP，按同一标准清出发布池
- Modify: `services/engtools/src/engtools/CommonTool.py:94`（删 `SopRunTool` 注册类）
- Modify: `services/sop-core/src/sop_core/sop_loader.py:20`（`_FALLBACK_KNOWN_TOOLS` 去掉 `"sop_run"`）

- [ ] 留档：`mkdir -p docs/archive/meta-sop-md-2026-10 && cp data/platform/sops/raw/meta_*.md data/platform/sops/raw/code_review.md data/platform/sops/raw/math_sop.md data/platform/sops/raw/market_research.md docs/archive/meta-sop-md-2026-10/`
- [ ] 先 grep 测试引用：`grep -rn "code_review\|math_sop\|market_research" tests/ services/*/tests --include="*.py"`；有用例引用则保留该文件并为其补 json 转正（steps→tool auto），无引用则删
- [ ] 删 raw md×6 + `json/market_research.json` + index.json 对应条目（或调 `refresh_index()` 重建）
- [ ] 删 `SopRunTool` 类与 `_FALLBACK_KNOWN_TOOLS` 中的 `"sop_run"`——此后 raw 单步壳（tool=sop_run）过不了 `_is_known_tool`，空壳无法再进发布池，假成功通道关闭（json 真相源的其余 SOP 不受影响）
- [ ] 跑 `pytest tests/unit/test_unit_sop_loader_status.py tests/unit/test_unit_sop_validator.py -q`，预期 PASS（若有用例断言 sop_run 可注册，同步改用例）
- [ ] Commit: `fix(sop): 移除 meta SOP 空壳与 sop_run 桩，关闭路由假成功通道`

## 4. 阶段 1：sop-api 解寄生（2-3 天）

### Task 1.1 新建服务骨架

**Files:**
- Create: `services/sop-api/main.py`
- Create: `services/sop-api/README.md`
- Modify: `docker/docker-compose.yml`（新增服务）
- Modify: `docker/Dockerfile.backend`（若 COPY 清单按服务列举，需补 sop-api；若整仓 COPY 则无需改——动手前先读该文件确认）

```yaml
# docker/docker-compose.yml 新增（与 aichat-api 同款骨架）
  sop-api:
    build:
      context: ..
      dockerfile: docker/Dockerfile.backend
    image: angineer-sop-api:latest
    container_name: angineer-sop-api
    restart: unless-stopped
    ports:
      - "127.0.0.1:8792:8792"
    command: ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8792"]
    working_dir: /app/services/sop-api
    volumes: # 照抄 compose 里 aichat-api 段的 volumes（data 卷同源），
             # sop-api 对 data/platform/sops 为唯一写者
    healthcheck: GET http://localhost:8792/health
```

- [ ] `services/sop-api/main.py`：FastAPI app + `/health` + 挂载从 aichat-api 平移来的路由
- [ ] 本地起服务，`curl 127.0.0.1:8792/health` 返回 200
- [ ] Commit: `feat(sop-api): 新增 SOP 数据面服务骨架（:8792）`

### Task 1.2 平移 sop_routes 与数据面端点

**Files:**
- Create: `services/sop-api/sop_routes.py`（自 `services/aichat-api/sop_routes.py` 平移）
- Modify: `services/aichat-api/main.py`（删 `from sop_routes import sop_router` 与 `app.include_router(sop_router, ...)`）
- Delete: `services/aichat-api/sop_routes.py`

- [ ] 平移时保留行为逐字节不变：导入解析（LLM）、`/steps/parse`、审核+审计、文件夹管理、delete-preview、`/generate`、`/generate-from-doc`（阶段 1 仍带 `docs_core.step07_graph` import，阶段 2 剪）
- [ ] `SOP_BASE_DIR` 解析改为 env `SOP_DATA_DIR` 优先（容器内指向挂载的 `data/platform/sops`），与现值兼容
- [ ] 删掉模块级 `_sop_loader`，服务内单实例（消除双 loader 问题在 sop 侧的半个；aichat 侧在 Task 1.3 消掉）
- [ ] 全量跑 sop 相关单测：`pytest tests/unit -k "sop" -q` 预期 PASS
- [ ] 服务器验证顺序（零停机）：先起 sop-api 容器 → nginx `location /api/sops/` 切到 `127.0.0.1:8792`（ai-proxy-locations.conf，改完 `nginx -t && systemctl reload nginx`）→ 管理页回归（建/导/审/删）→ 观察 1 天 → aichat-api 摘挂载重建
- [ ] Commit: `refactor(sop): SOP 数据面从 aichat-api 迁出为独立 sop-api`

### Task 1.3 aichat 执行面改走 HTTP 取 SOP 列表（D2）

**Files:**
- Create: `services/aichat-api/sop_api_client.py`
- Modify: `services/aichat-api/main.py:116-117`（`sop_loader = SopLoader(...)` 替换为 HTTP 客户端包装）

```python
# services/aichat-api/sop_api_client.py 核心形态
class SopApiClient:
    """经 sop-api 取 published SOP；失败降级末次快照（比直读文件更稳）。"""
    def __init__(self, base_url: str, ttl: float = 300.0): ...
    def load_published(self) -> list:  # 返回 SOP pydantic 对象列表
        # TTL 内返回缓存；过期则 GET {base}/api/sops/full?status=published
        # 成功 → 重建缓存+写快照；失败 → 返回末次快照并告警
```

- [ ] sop-api 侧补只读端点 `GET /api/sops/full?status=published`（返回完整 SOP JSON 数组，含 steps/blackboard；实现=`_scan_json_sops` 的全量版，逐 id 读 json 文件）。**路由顺序地雷：必须声明在 `@sop_router.get("/{sop_id}")`（平移后的 sop_routes.py:593）之前，否则 `"full"` 被当作 sop_id 吞掉**——同文件 `/delete-preview` 已示范此顺序约定
- [ ] aichat-api 的 `sop_loader` 引用点（`main.py:360-361,571` 等）改为 `sop_api_client.load_published()`；`make_policy_config_factory` 的 `sop_loader` 参数传 `None` 并在适配器内走 `sops=` 列表（`SopRunnerAdapter` 已支持）
- [ ] **evals_routes.py:63 的第三个 loader 实例一并转换**：`_intent_sop_loader` 改用同一 `SopApiClient`（评测路径与生产同源，不再各自直读文件）
- [ ] 降级演练：停 sop-api 容器，聊天 SOP 执行用快照照常工作，日志出现降级告警
- [ ] `.env.example` 登记 `SOP_API_URL`（容器内默认 `http://sop-api:8792`，本机 dev `http://127.0.0.1:8792`）
- [ ] Commit: `feat(aichat): 执行面 SOP 列表改经 sop-api HTTP + 快照兜底`

**阶段 1 验收**：管理页四类操作回归全过；聊天 SOP 执行路径 night 小集读数持平；停 sop-api 聊天不挂（快照兜底）；aichat-api 重启不再影响 SOP 管理面。

**回滚**：nginx location 切回 8791 即回到现状（sop_routes 在 aichat 的旧版本随回滚部署恢复）。

## 5. 阶段 2：剪跨模块耦合（1-2 天）

### Task 2.1 sop-core 定义图谱端口 Protocol

**Files:**
- Create: `services/sop-core/src/sop_core/graph_port.py`

```python
"""图谱只读端口：sop-core 不 import docs_core，宿主/接入层注入实现。"""
from typing import Any, Dict, List, Optional, Protocol

class GraphReader(Protocol):
    def get_entity_by_name(self, name: str) -> Optional[Any]: ...
    def list_entities_by_doc(self, library_id: str, doc_id: str) -> List[Any]: ...
    def get_frameworks_by_doc(self, library_id: str, doc_id: str): ...
```

### Task 2.2 sop_path_generator 去 docs_core 化

**Files:**
- Modify: `services/sop-core/src/sop_core/sop_path_generator.py:6-7`（删两行 import）
- Modify: `services/sop-core/src/sop_core/sop_path_generator.py`（`EntityLayer.ACTION` → 模块常量 `ACTION_LAYER = "action"`，与调用方对齐；`DEFAULT_LLM_CONFIG` → 构造参数 `llm_config`，缺省 None 走纯规则骨架）

- [ ] 实体 layer 判断改字符串比较（docs-api 返回的 layer 本就是字符串）
- [ ] `store` 参数类型注解改 `GraphReader`；`generate_sops_from_doc` 内 `e.layer == EntityLayer.ACTION` 等处同步替换
- [ ] 跑 `pytest tests/knowledge_graph/test_sop_path_generator.py -q` 预期 PASS（该测试本就以 stub store 注入，Protocol 化后应原样通过；若断言了 EntityLayer 枚举则改为字符串）

### Task 2.3 docs-api 补 frameworks 只读端点

**Files:**
- Modify: `services/docs-api/graph_routes.py`（新增）

```python
@graph_router.get("/frameworks")
async def list_frameworks(library_id: str, doc_id: str):
    """按文档列 framework 层实体（SOP 路径来源）。"""
    entities = _get_store().get_frameworks_by_doc(library_id, doc_id)
    return [
        {"entity_id": e.entity_id, "name": e.name, "layer": e.layer.value, "aliases": e.aliases,
         "status": e.status.value}
        for e in entities
    ]
```

（序列化形态照抄同文件 `/entities` 端点的内联字典写法。）

- [ ] 返回形态与现有 `/entities` 端点的序列化方式对齐（读该文件既有 `_doc_name_map` 用法后照抄）
- [ ] `curl "127.0.0.1:8790/api/graph/frameworks?library_id=...&doc_id=..."` 返回 200

### Task 2.4 sop-api 图谱改走 HTTP

**Files:**
- Create: `services/sop-api/docs_graph_client.py`（httpx，`trust_env=False`，同 eec9438 教训）
- Modify: `services/sop-api/sop_routes.py`（删 `_get_kg_store` 与 `docs_core.step07_graph` 两处 import）

- [ ] `/generate`：实体层信息经 `GET /api/graph/entities/search` 或按名查询端点获取；`SopPathGenerator(store=http_graph_reader)` 注入适配 `GraphReader` 的 httpx 实现
- [ ] `/generate-from-doc`：412 预检逻辑（有无图谱/ACTION 实体）改经 `GET /api/graph/entities/all` 与 `/api/graph/frameworks`
- [ ] grep 验证：`grep -rn "docs_core" services/sop-core/src services/sop-api/` 零命中
- [ ] Commit: `refactor(sop): sop-core/sop-api 剪断 docs_core 直连，图谱改经 docs-api HTTP`

### Task 2.5 边界回归测试（防复发）

**Files:**
- Create: `tests/unit/test_unit_sop_core_boundary.py`

```python
"""模块边界守卫：sop-core/sop-api 不得直连 docs_core/engtools 内部模块。"""
import pathlib

SOP_CORE = pathlib.Path("services/sop-core/src/sop_core")
FORBIDDEN = ("from docs_core", "import docs_core", "from engtools import")

def test_sop_core_no_docs_core_import():
    for f in SOP_CORE.rglob("*.py"):
        text = f.read_text(encoding="utf-8")
        for bad in FORBIDDEN[:2]:
            assert bad not in text, f"{f.name} 违例: {bad}"
```

- [ ] pytest PASS；把 `services/sop-api/` 同样纳入扫描
- [ ] Commit: `test(sop): 模块边界守卫测试`

**阶段 2 验收**：干净 venv `pip install -e services/sop-core` 成功且 `import sop_core` 不带 docs-core 也能工作（loader/parser/validator 全单测过）；边界测试绿。

## 6. 阶段 3：L4 工厂车道（3-5 天；开工前按本节出细化施工单）

> 本节为设计基线与接口契约。阶段 1/2 落地后，按此出 Task 级 TDD 施工单再动手。

### 6.1 接口契约（sop-api）

```
POST /api/sops/synthesize
  body: {query: str, library_id: str, doc_ids?: list[str]}
  200: {sop: <SOP JSON 结构化对象>}            # 不落盘，临时对象
  412: {error: "no_path", reason: str}          # 图谱无路径/实体未命中 → 运行时回落
  422: {error: "invalid_sop", problems: [...]}  # 校验未过

POST /api/sops/crystallize
  body: {sop: <SOP JSON>, source_query: str, review_note?: str}
  200: {id: str, status: "draft"}               # 落盘为 draft，进人工审核流
```

### 6.2 合成管线（sop-api 内，sop-core 新模块 `path_selector.py` + 既有件组装）

```
query
 ├─ 实体链接：GET docs-api /api/graph/entities/search?q=...（取 TOP-N）
 ├─ 路径选择：ACTION/framework 层骨架路径打分（TF-IDF 粗筛 + LLM 精排，复用 route() 两段式模式）
 ├─ 骨架生成：SopPathGenerator.generate_sop_skeleton（既有）
 ├─ 逐步细化：对每步调既有 /steps/parse 同款 LLM 解析（tool/inputs/outputs）
 ├─ 契约自检：validate_sop_data（既有闸）+ blackboard.required 闭包
 └─ 失败任何一步 → 412/422，绝不返回半成品
```

### 6.3 运行时接线（回调注入，库不做 sop-api HTTP）

挂点在 `SopRunnerAdapter.sop_execute`（`angineer_core/agent_tools.py:1253`，**在 angineer-core 库内**）。库层不得直连 sop-api（守自己的铁律），故 L4 能力以回调注入：

- `SopRunnerAdapter.sop_execute(...)` 新增参数 `synth_callback: Optional[Callable[[str, str, list], Dict]] = None`（签名：`(query, library_id, doc_ids) → {"sop": <SOP JSON>} | None`）；
- handler 内 route 未命中分支：`synth_callback is None` → **早退返回现行为 error dict（与今天逐字节一致，且由构造保证：不注入就没有新代码路径的副作用）**；非 None → 调回调；返回含 `sop` → 构造 `SOP` 对象直接 `run_sop`（**不要求 published**，执行器本就不检查），成功后回调方负责 crystallize，返回体标 `l4_synth: true`；回调返回 None → 现行为 error；
- **注入发生在 aichat-api 装配层**（`agent_configs.py` 调 `sop_execute(...)` 处）：开关 `ANGINEER_SOP_L4_SYNTH=1` 时才注入回调实现（内部调 `POST /api/sops/synthesize`，复用 `SopApiClient` 的 base_url；成功后异步 `POST /api/sops/crystallize`，附 source_query 与 trace 摘要）。开关关 = 不注入 = 库内零新路径。
- 预算（装配层回调内实现）：每问题至多 1 次 synthesize；内部 LLM 调用步数上限（默认 8）；总超时沿用 `timeout_s=300`。
- 观测：trace 与 sop_trace 标 `l4_synth` 来源；执行结果同样过 complex 档既有 `final_answer_guard`（证据闸，enforce_evidence=True）——动手时核对 sop_execute 路径上该闸确实生效。
- 门禁纪律：L4 读数只报不改门禁；对照实验预注册（判据跑前写死 + 带 complex 档参照臂，20 题海港域起步）。

**阶段 3 验收**：预注册对照不回退；**开关关闭时行为一致——单测断言早退路径：`synth_callback=None` 时未命中分支返回的 dict 与现实现逐键相等**；开关开启时 412/None 回落到同一 error dict；crystallize 产物进 draft 审核流可人工发布。

## 7. 阶段 4：sop-core 独立发包（0.5-1 天）

- [ ] **前置核查（开工先做）**：angineer-core 独立仓远端已到 v0.1.2、PyPI 最新 0.1.2（2026-10-12 本机核实），而主仓 `services/angineer-core/pyproject.toml` 仍 0.1.1——按 `git diff split/core HEAD:services/angineer-core/src` 判内容漂移，先对齐（或确认仅版本字段漂移）再发包
- [ ] `services/sop-core/pyproject.toml`：依赖行 `angineer-docs-core` → `angineer-core>=0.1.1`（干净 venv 实装会拉到 0.1.2 现货，满足语义） + `angineer-ai-inference>=0.2.2`
- [ ] 删 `services/sop-core/src/sop_core/sop_loader.py:9` 的 `sys.path.append` hack（以 grep 行号为准）
- [ ] 独立仓库 `angineer-sop-core`：`scripts/sync-standalone.ps1` 的 `$SourcePathOverrides` 加 `'sop-core' = 'services/sop-core'`；独立仓库侧照 ai-inference 模式放 `publish.yml`（OIDC trusted publishing + tag 与 pyproject 版本一致性校验）、LICENSE（MIT）、CI
- [ ] **版本号 0.1.0 首发需用户确认**（AGENTS.md 约定；未发布过，无占用）
- [ ] PyPI 侧配 trusted publisher（用户操作）
- [ ] 干净 venv 验收：`pip install angineer-sop-core` → `import sop_core; sop_core.SopLoader(...)` 可用，依赖自动拉 angineer-core（PyPI 现货已核实存在：0.1.0/0.1.1/0.1.2）

## 8. 风险与回滚

| 风险 | 缓解 | 回滚 |
| --- | --- | --- |
| 部署顺序错导致 /api/sops 404 | 零停机顺序：先起 sop-api → nginx 切流 → 观察 → aichat 摘挂载 | nginx location 切回 8791 |
| sop-api 挂导致聊天不能跑 SOP | HTTP + 末次快照兜底（Task 1.3） | 快照常驻，无需回滚 |
| 双写（阶段 1 切换窗口内 aichat 旧代码仍写文件） | 摘挂载前 nginx 已切流，写路径只剩 sop-api | — |
| L4 合成质量不可控 | 默认关（D3）+ 每问 1 次 + 步数上限 + 证据闸 + draft 人工审核 | 开关回 0 即回到纯 complex 兜底 |
| 评测/离线工具直读 sops 文件（读侧） | 离线只读容忍，写单点在 sop-api；后续统一走 HTTP | — |
| sync 脚本对 Python 包的覆盖差异 | 照 ai-inference 先例（同为 services/ 下 Python 包） | — |

## 9. 明确不做（范围外）

- 执行器 SopRunner 迁出 angineer-core（执行是运行时能力，迁移=造第二个 agent 运行时）
- L4 循环/重试语义（校验器禁环维持；子问题循环另立项）
- skill 执行态（md 不编译直接喂 agent——另行立项）
- classifier 深层港口逻辑外置（船型推断/备淤正则/停用词——另行立项）
- SOP 存储迁 sqlite、文件锁（sop-api 单写者后风险大降，先观察）
- 文档站/UI 改版（sop-ui 只做 researcher 组件删除）

## 10. 工作量与里程碑

| 阶段 | 量 | 独立价值 |
| --- | --- | --- |
| 0 清理 | 0.5 天 | 堵假成功陷阱、仓库减负 |
| 1 解寄生 | 2-3 天 | SOP 管理面独立部署，聊天重启不再殃及 |
| 2 剪耦合 | 1-2 天 | sop-core 可独立安装，违例清零 |
| 3 L4 车道 | 3-5 天 | 找不到 SOP 的复合题有了结构化出路 |
| 4 发包 | 0.5-1 天 | SOP 栈可单独售卖 |

合计约 7-11 个工作日；阶段间可暂停，0/1/2 无行为变化（除删除空壳），3 是唯一带实验性质、需预注册对照的阶段。
