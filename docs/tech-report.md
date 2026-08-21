# AnGIneer 技术报告

> 版本基线：**v0.2.7** · 更新日期：2026-08-21
>
> 本文是系统级技术报告：先用一张模块关系图交代整体架构，再按模块讲清各自的核心链路。各模块的深度技术细节请跳转文内链接（详见各章末尾"深入阅读"）。

---

## 1. 核心架构

### 1.1 模块关系图

```mermaid
flowchart TB
    subgraph UI["用户界面层"]
        UW["user-web 用户工作台<br/>3005"]
        AW["admin-web 管理后台<br/>3002"]
    end
    subgraph GW["服务网关层"]
        DA["docs-api 8790<br/>知识库 / 解析 / 图谱 / v1 外部 API"]
        AA["aichat-api 8791<br/>Agent 对话 / SOP / Evals / Dream Cycle"]
    end
    subgraph BIZ["业务模块层"]
        CORE["angineer-core<br/>主调度"]
        DOCS["docs-core<br/>知识库"]
        SOP["sop-core<br/>经验库"]
        EVAL["evals-core<br/>评测"]
        TOOL["engtools<br/>工程工具"]
        GEO["geo-core<br/>世界底座"]
    end
    subgraph BASE["基础设施层"]
        AI["ai-inference<br/>大模型统一路由"]
    end

    UW --> DA & AA
    AW --> DA & AA
    DA --> DOCS & CORE
    AA --> CORE & SOP & EVAL & TOOL & GEO
    CORE --> AI
    DOCS --> AI
```

> 说明：AnGIneer-TreeCore 是树操作的通用基础设施（零外部依赖），不参与业务模块关系，故未列入上图。

### 1.2 对外服务边界

| 模块 | 对外暴露 | 鉴权方式 |
| :--- | :--- | :--- |
| **docs-api** | `/api/v1/*`（文档解析/产物/内容） | `X-API-Key`（管理后台签发，绑定库隔离） |
| **docs-api** | `/api/knowledge`、`/api/graph`（知识库/图谱） | 内部代理（前端经 vite/nginx 转发） |
| **aichat-api** | `/api/chat/agent`、`/api/sops`、`/api/evals`、`/api/dream-cycle` | 内部代理（不对外直连） |
| **user-web / admin-web** | 浏览器访问的 Web 界面 | 生产环境：管理端 IP 白名单 + Basic Auth |

两个 FastAPI 网关默认只绑定本机回环（`127.0.0.1`），公网只暴露 nginx 80 端口。

---

## 2. AnGIneer-Core 主调度模块

### 2.1 Agent 化问答链路

```mermaid
flowchart TB
    U["用户输入"] --> F["user-web / admin-web 聊天面板"]
    F -->|"POST /api/chat/agent (SSE)"| S["AgentSession 会话池<br/>多轮记忆 / steer / cancel"]
    S --> L["run_agent_loop<br/>LLM 流式生成 + 工具编解码 + 预算闸门"]
    L --> C{"意图分级 L0-L4"}
    C -->|"L1 概念/正文"| A1["L1 Agentic RAG"]
    C -->|"L2 规范查询"| A2["L2 条款/查表链路"]
    C -->|"L3 标准作业"| A3["SOP 执行链路"]
    C -->|"L4 综合大题"| A4["L4 Agentic 编排"]
    A2 -->|"失败回退"| A1
    A3 -->|"失败回退"| A1
    A1 --> T["工具：knowledge_search / table_search / entity_search"]
    A4 --> T2["工具：sop_execute / calculator / conditional"]
    T --> R["五路召回：dense + sparse + clause + table + formula"]
    R --> F2["RRF 加权融合 + 重排"]
    F2 --> E["证据构建 + 引用定位"]
    E --> G{"证据是否足够"}
    G -->|"是"| Ans["带引用答案 + 置信度"]
    G -->|"否"| Ref["拒答 / 沿执行计划回退"]
```

### 2.2 分级路由策略

| 层级 | 问题类型 | service_mode | 主处理链路 |
| :--- | :--- | :--- | :--- |
| **L0** | 闲聊寒暄 | `casual_chat` | 直接 LLM 对话，不检索 |
| **L1** | 概念解析 / 定位问答 | `semantic_retrieval` | 多路召回 → 融合 → LLM 基于证据作答 |
| **L2** | 条款应用 / 规范查询 | `structured_lookup` | 条款/表格结构化查证 → 失败回退 L1 |
| **L3** | 标准工程计算 | `standard_sop` | SOP 召回 → 精排 → 参数抽取 → 执行 |
| **L4** | 复杂复合任务 | `dynamic_orchestration` | Agent 循环动态组合多能力链路 |

> 深入阅读：[docs/agent-harness.md](agent-harness.md)（L0~L4 策略、Attempt 状态机、事件协议、守卫）

---

## 3. AnGIneer-Docs 知识库模块

### 3.1 一体化文档解析管线

```mermaid
flowchart LR
    SRC["源文件<br/>PDF / DOCX / PPTX / XLSX"] --> CV["格式转换<br/>LibreOffice → PDF"]
    CV --> MU["MinerU 解析<br/>hard"]
    MU --> PO["PoPo 强化<br/>soft · 失败回滚"]
    PO --> SOLO["Solo 结构化<br/>hard · 唯一构建者"]
    SOLO --> FTS["SQLite + FTS<br/>hard"]
    FTS --> VEC["向量索引<br/>soft"]
    VEC --> GR["知识图谱<br/>soft"]
```

要点：hard 阶段失败终止后续、soft 阶段失败仅标记自身；支持单阶段重试、断点恢复、GPU 排队与阶段级可视化。

### 3.2 知识图谱模块

```mermaid
flowchart LR
    DOC["文档结构化产物"] --> SEED["种子共现兜底<br/>70+ 工程术语"]
    SEED --> LLM1["LLM 实体 + 关系抽取"]
    LLM1 --> V3["三重验证<br/>V1 跨域 / V2 预测力 / V3 独特性"]
    V3 --> ZK["Zettelkasten 跨段语义连接"]
    ZK --> E5["cangjie E1-E5 提取<br/>原则/案例/反例/术语/框架"]
    E5 --> DB["图谱落库<br/>按 library_id + doc_id 隔离"]
    DB --> REV["人工审核<br/>/api/graph/review"]
```

### 3.3 自进化模块（Dream Cycle）

```mermaid
flowchart LR
    CRON["每日定时<br/>0 2 * * *"] --> CHK["5 项健康检查"]
    CHK --> DEDUP["实体去重"]
    CHK --> CTRD["矛盾关系"]
    CHK --> ORPH["孤立实体"]
    CHK --> STALE["过期知识"]
    CHK --> SOPH["SOP 健康统计"]
    DEDUP & CTRD & ORPH & STALE & SOPH --> RPT["JSON 报告 + 审计日志"]
    RPT --> ACT["自动操作（仅标记不物理删除）<br/>或人工确认"]
```

> 深入阅读：[docs/parse-pipeline.md](parse-pipeline.md) · [docs/popo-pipeline.md](popo-pipeline.md) · [docs/knowledge-data-model.md](knowledge-data-model.md)

---

## 4. AnGIneer-SOPs 经验库模块

### 4.1 SOP 自动生成链路

```mermaid
flowchart LR
    GRAPH["知识图谱<br/>framework / ACTION 实体链"] --> CAND["候选 SOP 识别"]
    CAND --> GEN["规则骨架生成 / LLM 生成<br/>含原则/案例/反例/术语标注"]
    GEN --> BB["黑板变量依赖提取<br/>required / outputs"]
    BB --> VAL["SOP 校验<br/>步骤图 / 工具契约"]
    VAL --> REV2["审核闸门<br/>POST /{sop_id}/review"]
    REV2 --> LIB["可执行库<br/>data/sops"]
    LIB --> RUN["运行时执行<br/>sop_run + calculator / table_lookup / conditional"]
```

### 4.2 主要能力

| 能力 | 说明 |
| :--- | :--- |
| 自动生成 | 从文档图谱识别 framework 路径或 ACTION 实体链生成 SOP JSON |
| 解析引擎 | Markdown SOP → 结构化执行计划（6 种工具类型） |
| 条件分支 | 精确匹配 → 排除法 → LLM 语义匹配三级降级 |
| 审核与审计 | LLM 生成的 SOP 需审核后才进入可执行库，全程留痕 |

> 相关规划文档：[docs/sop-extractor-plan.md](sop-extractor-plan.md)

---

## 5. AnGIneer-Evals 评测引擎模块

### 5.1 评测链路

```mermaid
flowchart LR
    DS["题集<br/>注册考试 2019/2020 + 检索基准集"] --> RUN["评测运行<br/>异步启动 / 轮询进度"]
    RUN --> PIPE["被测链路<br/>同构调用 policy_query（不走 HTTP）"]
    PIPE --> MET["多维度评测"]
    MET --> RET["检索评测<br/>Hit@1/3/5 · MRR · citation_hit"]
    MET --> SOPE["SOP 执行评测"]
    MET --> ANS["回答语义评测"]
    RET --> BUCKET["失败分桶<br/>missed_exact_target / wrong_section_bias / ..."]
    BUCKET & SOPE & ANS --> STORE["结果落库 SQLite"]
    STORE --> CMP["两次运行对比看板<br/>分数差异 + 题目级变化"]
```

> 深入阅读：[docs/retrieval-chain.md](retrieval-chain.md)（检索评测指标与失败分桶的踩坑记录）

---

## 6. AnGIneer-AI 大模型统一路由模块

```mermaid
flowchart LR
    ENV["LLM_CONFIGS<br/>多模型 JSON 配置"] --> ROUTE["统一路由<br/>优先级 / enabled"]
    ROUTE --> CLIENT["LLM 客户端<br/>重试 · 熔断 · 三级超时 · 流式"]
    CLIENT --> UP["OpenAI 兼容端点"]
    EMB["在线 Embedding / Reranker"] --> DEG["故障自动降级<br/>hash embedding（权重 0.05）<br/>本地 phrase rerank"]
```

要点：`ai-inference` 是 AI 推理唯一真相源（零外部依赖）；Prompt 统一资产化（`prompts/` 带版本号注册），改动 prompt 必须升版本号，CI 强制审计。

> 深入阅读：[docs/llm-gateway.md](llm-gateway.md)

---

## 7. 技术架构与仓库布局

### 7.1 依赖方向（强约束）

```text
ai-inference（AI 推理唯一真相源，零外部依赖）
    ↑
angineer-core / docs-core / evals-core / sop-core / engtools / geo-core
    ↑
docs-api / aichat-api（服务网关）
    ↑
user-web / admin-web（用户界面层）
```

### 7.2 仓库布局

| 目录 | 内容 |
| :--- | :--- |
| `apps/` | user-web（3005）、admin-web（3002）、shared（端口契约 + API 客户端） |
| `packages/` | docs-ui / aichat-ui / sop-ui / evals-ui / geo-ui / engtools-ui / ui-kit |
| `services/` | 两个 FastAPI 网关 + ai-inference / tree-core / angineer-core / docs-core / sop-core / evals-core / geo-core / engtools |
| `data/` | knowledge_base / sops / evals / dream_cycle / api_keys.sqlite |
| `docs/` | 本报告与各模块技术文档 |

---

## 8. 路线图

| 阶段 | 已完成 / 进行中 | 未来 |
| :--- | :--- | :--- |
| **v0.1** | 规范问答基础版：文档解析入库、知识图谱、SOP 引擎、L0-L4 分级、AI 对话、评测框架 | — |
| **v0.2** | Agent 化问答链路、五路检索 + 融合重排、SOP 审核/审计、Prompt 资产化、一体化文档解析管线 + PoPo 强化、注册考试题集评测、Dream Cycle 巡检（当前基线 v0.2.7） | — |
| **v0.3** | geo-core GIS 断面算量工具、GIS 视图骨架 | Cesium 三维世界模型、地理信息自主查询、空间计算联动 |
| **v0.4** | — | 设计报告自动编制（工可 / 初设） |
| **v0.5** | — | CAD 出图算量闭环（**正式版**） |
| **v1.0+** | — | 多专业覆盖、精度与稳定性、SaaS 化多租户 |
