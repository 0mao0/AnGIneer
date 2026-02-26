# 🏗️ AnGIneer: 工程领域的AI工程师

**AnGIneer** (AGI + Engineer) 是专为严谨工程领域打造的AI操作Agent系统。它将小型语言模型 (SLM)、标准作业程序 (SOPs)、工程工具链 (EngTools) 与地理信息世界 (GeoWorld) 深度融合，致力于为工程师提供**过程可控、结果精确、具备环境感知能力**的自动化解决方案。

> *"Human Defines SOP, AnGIneer Executes with Precision."*

---

## 1. 核心理念 (Philosophy)

- **确定性优先 (Deterministic First)**: 在工程领域，"准确"优于"创造"。AnGIneer 通过严格遵循 SOP，杜绝 LLM 的幻觉风险。
- **混合智能 (Hybrid Intelligence)**: **Code** 负责严谨逻辑与计算，**LLM** 负责意图理解、非结构化数据解析与人机交互。
- **环境感知 (Context Aware)**: 打通数字世界与物理世界（GeoWorld），让计算不再是真空中的数学题，而是基于真实地理环境的工程决策。

---

## 2. 核心架构 (Architecture)

AnGIneer 不仅仅是一个 Agent，更是一套连接知识、工具与物理世界的工业级 OS。系统采用 **Monorepo (单体仓库)** 架构，由以下核心模块构成：

```mermaid
flowchart TD
    %% 样式定义
    classDef user fill:#e1f5fe,stroke:#01579b,stroke-width:2px,color:#000
    classDef frontend fill:#fff3e0,stroke:#ef6c00,stroke-width:2px,color:#000
    classDef core fill:#f3e5f5,stroke:#6a1b9a,stroke-width:2px,color:#000
    classDef service fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px,color:#000

    U(["👤 用户"]) --> W["🖥️ Web 控制台"]
    W --> A["⚡ API 服务"]
    A --> D["🧠 调度器<br>Dispatcher"]
    D --> M["💾 记忆系统<br>Memory"]
    D --> S["📋 SOP 引擎"]
    D --> Doc["📚 知识引擎"]
    D --> G["🗺️ GIS 引擎"]
    D --> E["🔧 工程工具"]

    class U user
    class W frontend
    class A,D,M core
    class S,Doc,G,E service
```

### 2.1 子系统矩阵 (Subsystem Matrix)

| 子系统 | 对应服务 | 核心职责 | 独立性 |
| :--- | :--- | :--- | :--- |
| **AnGIneer-SOP** | `services/sop-core` + `packages/sop-ui` | **流程大脑**。负责 SOP 的定义、解析与可视化编排。 | ⭐⭐⭐ |
| **AnGIneer-Tools** | `services/engtools` + `packages/engtools-ui` | **专业工具**。高精度工程计算器、脚本库与交互界面。 | ⭐⭐ |
| **AnGIneer-Docs** | `services/docs-core` + `packages/docs-ui` | **行业记忆**。基于AnGIneer数据标准的规范自动解析与知识库管理。 | ⭐⭐⭐⭐ |
| **AnGIneer-Geo** | `services/geo-core` + `packages/geo-ui` | **世界底座**。集成 GIS 数据、水文气象信息与地图展示。 | ⭐⭐⭐⭐ |
| **AnGIneer-Report** | (Planned) | **交付终端**。自动生成工程报告。 | ⭐⭐⭐ |

### 2.2 核心模块架构 (dispatcher.py)

**调度器 (Dispatcher)** 是 AnGIneer OS 的执行引擎，负责 SOP 步骤的编排、工具调用与上下文更新。

```mermaid
flowchart LR
    %% 样式定义
    classDef process fill:#e3f2fd,stroke:#1565c0,stroke-width:2px,color:#000
    classDef action fill:#fff8e1,stroke:#f9a825,stroke-width:2px,color:#000
    classDef handler fill:#fce4ec,stroke:#c2185b,stroke-width:2px,color:#000
    classDef external fill:#f3e5f5,stroke:#7b1fa2,stroke-width:2px,color:#000

    %% 主流程 - 水平布局更紧凑
    D_INIT["🚀 初始化<br>run()"] --> D_RUN["▶️ 执行SOP<br>_execute_sop()"]
    D_RUN --> D_EXEC["⚙️ 执行步骤<br>_execute_step()"]
    D_EXEC --> D_SMART["🤖 智能执行<br>_smart_step_execution()"]

    %% 执行分支
    D_SMART --> D_ANALYZE["📊 分析执行<br>_analyze_execution()"]
    D_ANALYZE --> D_TOOL["🔧 工具执行<br>_execute_tool_safe()"]
    D_ANALYZE --> D_LLM["🧠 LLM调用<br>_smart_step_execution()"]

    %% Action处理器 - 简化为列表
    D_SMART --> D_HANDLERS["📋 Action处理器"]
    D_HANDLERS --> D_H1["return_value<br>返回值处理"]
    D_HANDLERS --> D_H2["ask_user<br>询问用户"]
    D_HANDLERS --> D_H3["search_knowledge<br>知识检索"]
    D_HANDLERS --> D_H4["execute_tool<br>执行工具"]

    %% 外部依赖
    MEM["💾 记忆系统<br>Memory"]
    LLM["🤖 LLM客户端<br>LLMClient"]
    TOOL["🧰 工具注册表<br>ToolRegistry"]

    D_EXEC -.-> MEM
    D_LLM -.-> LLM
    D_TOOL -.-> TOOL

    %% 样式应用
    class D_INIT,D_RUN,D_EXEC,D_SMART,D_ANALYZE process
    class D_TOOL,D_LLM action
    class D_HANDLERS,D_H1,D_H2,D_H3,D_H4 handler
    class MEM,LLM,TOOL external
```

**核心方法说明：**
| 方法 | 职责 | 依赖 |
|:---|:---|:---|
| `run(sop)` | SOP 执行主入口，遍历所有步骤 | Memory, SOP |
| `_execute_step(step)` | 根据步骤类型选择执行策略 | Step, Memory |
| `_smart_step_execution` | 智能步骤执行，使用策略模式处理不同 action | LLMClient |
| `_execute_tool_safe` | 安全执行工具，带错误处理 | ToolRegistry |
| `_extract_json_from_response` | 从 LLM 响应中提取 JSON | - |

---

### 2.3 核心模块架构 (classifier.py)

**意图分类器 (IntentClassifier)** 负责分析用户查询，匹配最合适的 SOP 并提取参数。

```mermaid
flowchart TD
    %% 样式定义
    classDef main fill:#e8eaf6,stroke:#3f51b5,stroke-width:2px,color:#000
    classDef data fill:#e0f2f1,stroke:#00796b,stroke-width:2px,color:#000
    classDef infra fill:#fff3e0,stroke:#f57c00,stroke-width:2px,color:#000

    %% 主流程
    C_ROUTE["🎯 路由入口<br>route()"] --> C_SELECT["🔍 意图识别<br>_select_sop()"]
    C_ROUTE --> C_EXTRACT["📤 参数提取<br>_extract_args_with_blackboard()"]

    %% 数据模型
    C_SOP_LIST["📋 SOP列表<br>SOP Index"]
    C_INTENT_RESP["📊 意图响应<br>IntentResponse"]
    C_ARGS_RESP["📋 参数提取响应<br>ArgsExtractResponse"]

    %% 基础设施
    C_LLM["🤖 LLM客户端<br>LLMClient"]
    C_PARSER["🔧 响应解析器<br>ResponseParser"]

    %% 连接
    C_SELECT -.-> C_LLM
    C_EXTRACT -.-> C_LLM
    C_SELECT -.-> C_INTENT_RESP
    C_EXTRACT -.-> C_ARGS_RESP
    C_ROUTE -.-> C_SOP_LIST

    %% 样式
    class C_ROUTE,C_SELECT,C_EXTRACT main
    class C_SOP_LIST,C_INTENT_RESP,C_ARGS_RESP data
    class C_LLM,C_PARSER infra
```

**核心方法说明：**
| 方法 | 职责 | 输入/输出 |
|:---|:---|:---|
| `route(query)` | 主路由入口 | query → (SOP, args, reason) |
| `_extract_args_with_blackboard` | 从查询中提取参数 | query, keys → args{} |

---

### 2.4 核心模块架构 (memory.py)

**记忆系统 (Memory)** 实现黑板模式，负责全局上下文、执行历史和临时工作记忆管理。

```mermaid
flowchart TD
    %% 样式定义
    classDef store fill:#e3f2fd,stroke:#1976d2,stroke-width:2px,color:#000
    classDef op fill:#f3e5f5,stroke:#7b1fa2,stroke-width:2px,color:#000
    classDef model fill:#e8f5e9,stroke:#388e3c,stroke-width:2px,color:#000

    %% 数据存储
    subgraph Store["💾 数据存储"]
        M_BB["📋 黑板<br>blackboard"]
        M_GC["🌍 全局上下文<br>global_context"]
        M_STEP_IO["🔄 步骤输入输出<br>step_io"]
        M_HIST["📜 执行历史<br>history"]
    end

    %% 核心操作
    subgraph Ops["⚙️ 核心操作"]
        M_UPDATE["📝 更新数据<br>update()"]
        M_RESOLVE["🔍 变量解析<br>resolve_variables()"]
        M_SYNC["🔄 同步上下文<br>sync()"]
    end

    %% 数据模型
    M_STEP_REC["📊 步骤记录<br>StepRecord"]
    M_UNDEF_ERR["⚠️ 未定义变量错误<br>UndefinedVariableError"]

    %% 连接
    M_UPDATE -.-> M_BB
    M_RESOLVE -.-> M_BB
    M_SYNC -.-> M_GC
    M_BB -.-> M_STEP_REC
    M_RESOLVE -.-> M_UNDEF_ERR

    %% 样式
    class M_BB,M_GC,M_STEP_IO,M_HIST store
    class M_UPDATE,M_RESOLVE,M_SYNC op
    class M_STEP_REC,M_UNDEF_ERR model
```

**核心功能说明：**
| 功能 | 描述 | 典型使用场景 |
|:---|:---|:---|
| `blackboard` | 步骤间数据共享的核心存储 | 步骤 A 输出 → 步骤 B 输入 |
| `resolve_variables()` | 解析 `${variable}` 语法 | 步骤输入参数动态替换 |
| `history` | 执行历史追踪 | 审计、回滚、调试 |
| `tool_working_memory` | 工具临时数据 | 复杂工具的中间状态 |

---

### 2.5 核心模块架构 (llm.py & response_models.py)

**LLM 客户端** 提供统一的大模型调用接口，支持多模型配置、熔断器、重试机制。

```mermaid
flowchart TD
    %% 样式定义
    classDef client fill:#e8eaf6,stroke:#3f51b5,stroke-width:2px,color:#000
    classDef cb fill:#fff3e0,stroke:#f57c00,stroke-width:2px,color:#000
    classDef parser fill:#e0f2f1,stroke:#00897b,stroke-width:2px,color:#000
    classDef model fill:#fce4ec,stroke:#d81b60,stroke-width:2px,color:#000

    %% 客户端
    subgraph Client["🤖 LLM客户端 LLMClient"]
        L_CHAT["💬 聊天<br>chat()"]
        L_RETRY["🔄 重试机制<br>retry"]
        L_TIMEOUT["⏱️ 超时控制<br>timeout"]
    end

    %% 熔断器
    subgraph CB["⚡ 熔断器 CircuitBreaker"]
        L_STATES{"🔄 状态机"}
        L_CLOSED["✅ 关闭状态<br>CLOSED"]
        L_OPEN["❌ 开启状态<br>OPEN"]
        L_HALF["⚠️ 半开状态<br>HALF_OPEN"]
    end

    %% 解析器
    subgraph Parser["🔧 响应解析器 ResponseParser"]
        L_EXTRACT["📤 提取JSON<br>_extract_json_from_response()"]
        L_VALIDATE["✓ 验证Schema<br>validate_schema()"]
    end

    %% 响应模型
    L_INTENT["🎯 意图响应<br>IntentResponse"]
    L_ACTION["⚡ 动作响应<br>ActionResponse"]
    L_ARGS["📋 参数提取响应<br>ArgsExtractResponse"]

    %% 连接
    L_CHAT -.-> L_RETRY
    L_RETRY -.-> L_STATES
    L_STATES -.-> L_CLOSED
    L_STATES -.-> L_OPEN
    L_STATES -.-> L_HALF
    L_CHAT -.-> L_EXTRACT
    L_EXTRACT -.-> L_VALIDATE
    L_VALIDATE -.-> L_INTENT
    L_VALIDATE -.-> L_ACTION
    L_VALIDATE -.-> L_ARGS

    %% 样式
    class L_CHAT,L_RETRY,L_TIMEOUT client
    class L_STATES,L_CLOSED,L_OPEN,L_HALF cb
    class L_EXTRACT,L_VALIDATE parser
    class L_INTENT,L_ACTION,L_ARGS model
```

**稳定性机制说明：**
| 机制 | 作用 | 配置项 |
|:---|:---|:---|
| 熔断器 (CircuitBreaker) | 防止级联故障 | failure_threshold, recovery_timeout |
| 重试 (Retry) | 自动恢复临时故障 | max_attempts, backoff_factor |
| 超时 (Timeout) | 避免长时间等待 | connect_timeout, read_timeout |

---

### 2.6 核心模块架构 (sop_loader.py & sop_parser.py)

**SOP 引擎** 负责标准作业程序的加载、解析与管理。

```mermaid
flowchart TD
    %% 样式定义
    classDef loader fill:#e3f2fd,stroke:#1976d2,stroke-width:2px,color:#000
    classDef parser fill:#f3e5f5,stroke:#7b1fa2,stroke-width:2px,color:#000
    classDef index fill:#fff8e1,stroke:#f9a825,stroke-width:2px,color:#000
    classDef model fill:#e8f5e9,stroke:#43a047,stroke-width:2px,color:#000

    %% 加载器
    subgraph Loader["📂 SOP加载器 SopLoader"]
        S_LOAD_ALL["📥 加载全部<br>load_all()"]
        S_REFRESH["🔄 刷新索引<br>refresh_index()"]
        S_PARSE_MD["📝 解析Markdown<br>_parse_markdown()"]
    end

    %% 解析器
    subgraph Parser["🔍 SOP解析器 SopParser"]
        S_PARSE_SOP["📋 解析SOP<br>parse_sop()"]
        S_PARSE_STEP["⚙️ 解析步骤<br>parse_step()"]
        S_EXTRACT_BB["📤 提取变量<br>extract_blackboard_vars()"]
    end

    %% 索引
    subgraph Index["📇 索引管理 Index"]
        S_INDEX_FILE["📄 索引文件<br>index.json"]
        S_META["🏷️ 元数据<br>metadata"]
    end

    %% 数据模型
    S_SOP["📋 SOP对象<br>SOP"]
    S_STEP["⚙️ 步骤对象<br>Step"]

    %% 连接
    S_LOAD_ALL -.-> S_INDEX_FILE
    S_REFRESH -.-> S_INDEX_FILE
    S_INDEX_FILE -.-> S_META
    S_PARSE_MD -.-> S_PARSE_SOP
    S_PARSE_SOP -.-> S_PARSE_STEP
    S_PARSE_STEP -.-> S_EXTRACT_BB
    S_PARSE_SOP -.-> S_SOP
    S_PARSE_STEP -.-> S_STEP

    %% 样式
    class S_LOAD_ALL,S_REFRESH,S_PARSE_MD loader
    class S_PARSE_SOP,S_PARSE_STEP,S_EXTRACT_BB parser
    class S_INDEX_FILE,S_META index
    class S_SOP,S_STEP model
```

**索引机制优势：**
| 特性 | 说明 | 收益 |
|:---|:---|:---|
| 懒加载 | 仅加载元数据，不加载完整内容 | 启动速度快 |
| 轻量级路由 | Router 只获取 SOP 描述 | 减少 Context Window 占用 |
| 按需解析 | 执行时才解析完整 SOP | 内存效率高 |

---

## 3. 开发路线图 (Roadmap)

### 阶段一：内核构建 (Core) - v0.1
*目标：构建 AnGIneer OS 的核心调度引擎 (Dispatcher)、意图识别（Classifier）、SOP解析引擎 (SOP-Parser)、数据标准（contextStruct）、记忆总线（Blackboard)和工具引擎（EngTools)，跑通最小闭环。*
- [✅] **混合调度器**: 实现 `Dispatcher`，支持 Tool/LLM 动态切换。
- [✅] **多LLM模型支持**: 支持任意LLM模型，目前已配置Qwen\Deepseek等，可无限扩展，并定义其与SOP、EngTools的交互协议`response_models.py`。
- [✅] **初建Engitools**: 支持计算器、查表、条件等工具等（Lite）。
- [✅] **黑板报机制**: 在`memory`实现Blackboard总线机制。
- [✅] **SOP标准协议**: 定义AnGIneer-SOP的Markdown/JSON协议规范。
- [✅] **数据标准**: 定义核心业务数据结构 (`Step`, `SOP`, `AgentResponse`) 与 LLM 响应结构 (`IntentResponse`, `ActionResponse`, `StepParseResponse`, `ArgsExtractResponse`)。
- [✅] **执行可视化（Lite）**: 注册考试题部分，可生成`Result.md`，实时透视决策链路。
- [🔨] **核心模块测试**: 完成5个注册考试题的测试。

### 阶段二：知识与视觉 (Docs & Vision) - v0.2
*目标：启动 `AnGIneer-Docs` 子系统，解决"数据源"问题。*
- [🔨] **标准制定**: 指定符合Dispatcher、SOP、EngTools的Docs交互标准。
- [ ] **深度文档解析**: 开发 PDF 解析器，精准提取规范条文与表格。
- [ ] **图表语义化**: 让 AI "读懂" 工程图表（曲线图、设计图）。
- [ ] **经验库构建**: 建立基于向量检索的历史案例库。

### 阶段三：交互与编排 (Interaction) - v0.3
*目标：启动 `AnGIneer-SOP` 前端，提供可视化的作业环境。*
- [ ] **Web 控制台**: 基于 Vue3 + Antd 的任务管理界面。
- [ ] **流程编辑器**: 拖拽式 SOP 设计器，降低规则制定门槛。
- [ ] **人机协作 (HITL)**: 支持暂停、断点调试与人工参数修正。

---

## 4. 快速开始 (Quick Start)
### 4.1 项目结构 (Project Structure)

本项目采用模块化单体仓库结构，便于独立维护与发布：

```text
AnGIneer/
├── apps/                   # 🚀 应用入口
│   ├── web-console/        # [前端] 主控台 (Vue3 + Ant Design Vue)
│   └── api-server/         # [后端] 主 API 网关 (FastAPI)
│
├── packages/               # 📦 前端组件包 (Vue 组件库，可独立发布到 npm)
│   ├── docs-ui/            # [知识引擎] 文档管理与解析可视化
│   ├── sop-ui/             # [SOP引擎] 流程编排与执行可视化
│   ├── geo-ui/             # [空间引擎] GIS 地图与图层管理
│   ├── engtools-ui/        # [专业工具] 工程计算器与工具界面
│   └── ui-kit/             # [基础组件] 共享 UI 组件库
│
├── services/               # 🧠 后端核心服务 (Python 包，可独立发布到 PyPI)
│   ├── angineer-core/      # [OS内核] 调度器、内存管理、基础架构【⚠当前v0.1的重点】
│   ├── sop-core/           # [SOP引擎] 流程解析器、验证器
│   ├── docs-core/          # [知识引擎] 文档解析、RAG 检索
│   ├── geo-core/           # [空间引擎] GIS 接口封装
│   └── engtools/           # [专业工具] 独立工程算法与脚本库
│
└── data/                   # 💾 数据存储
    ├── sops/               # SOP 流程定义文件
    ├── knowledge_base/     # 规范文档库
    └── geo_data/           # 地理空间数据
```

### 4.2 环境准备

```bash
git clone https://github.com/YourOrg/AnGIneer.git
cd AnGIneer

# 安装核心包 (开发模式)
pip install -e services/angineer-core/src
pip install -e services/sop-core/src
pip install -e services/docs-core/src
pip install -e services/geo-core/src
pip install -e services/engtools/src

# 安装 API Server 依赖
pip install -r apps/api-server/requirements.txt (如果存在)
```

### 4.3 运行测试

项目使用 pytest 进行测试，测试分为单元测试和集成测试两类：

```bash
# 运行所有测试
python -m pytest tests/unit/ tests/integration/ -v

# 只运行单元测试 (107 个测试)
python -m pytest tests/unit/ -v

# 只运行集成测试 (14 个测试)
python -m pytest tests/integration/ -v

# 运行特定测试文件
python -m pytest tests/unit/test_unit_dispatcher.py -v
python -m pytest tests/integration/test_03_dispatcher_verify.py -v
```

**测试结构：**
```
tests/
├── conftest.py              # pytest 配置文件
├── unit/                    # 单元测试 (107 个)
│   ├── test_unit_classifier.py
│   ├── test_unit_config.py
│   ├── test_unit_dispatcher.py
│   ├── test_unit_logger.py
│   ├── test_unit_memory.py
│   └── test_unit_response_parser.py
└── integration/             # 集成测试 (14 个)
    ├── test_00_llm_chat.py
    ├── test_01_tool_registration.py
    ├── test_02_sop_analysis.py
    ├── test_03_dispatcher_verify.py
    ├── test_04_intent_classifier.py
    └── test_05_Q1_with_reports.py
```

### 4.4 运行服务

1.  **配置密钥**: 在 `.env` 中设置 `LLM_API_KEY`。
2.  **启动 API Server**:
    ```bash
    python apps/api-server/main.py
    ```
3.  **启动 Web Console**:
    ```bash
    cd apps/web-console
    pnpm install
    pnpm run dev
    ```

---
*AnGIneer - Re-engineering the Future of Engineering.*
