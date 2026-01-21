# 📦 PicoAgent: 工程师的 AGI 助手

**小型 LLM + SOPs + GeoWorld = 节省工程师 50% 工作量 ≈ 工程师 AGI**

---

## 1. 项目愿景 (Vision)

PicoAgent 是一个**基于 SOP 的轻量级 Agent 执行引擎**，专为工程、设计等严谨行业打造。我们的目标是通过结合小型语言模型 (LLM)、标准作业程序 (SOPs) 和地理世界 (GeoWorld) 数据，为工程师提供高度确定性的自动化工具，显著提升生产力。

### 核心理念
- **Human Defines SOP, Agent Executes Tasks** (人定流程，Agent 执行)
- **确定性执行 (Deterministic)**: 反“智能涌现”和幻觉，严格遵循企业既定的标准作业程序。
- **混合架构 (Hybrid)**: 规则为主，AI 为辅。在确定性步骤中追求速度，在复杂决策时唤醒 AI。

---

## 2. 核心架构 (Architecture)

### 2.1 混合调度架构 (Hybrid Flow)

```mermaid
graph TD
    User[用户请求] --> Classifier[Intent Classifier (意图分类)]
    Classifier -->|匹配 SOP| Loader[SOP Loader (智能分析)]
    
    subgraph "Hybrid Execution Engine (混合执行引擎)"
        Loader -->|解析步骤 & 提取 Notes| Dispatcher[Dispatcher Agent]
        Dispatcher -->|规则判断| Check{需要 AI 介入?}
        
        Check -- No (确定性执行) --> ToolExec[直接调用工具]
        Check -- Yes (缺参数/有备注) --> LLM[LLM 决策核心]
        
        LLM -->|查阅规范| KnowledgeTool[Knowledge Search (知识检索)]
        LLM -->|查询数据| TableTool[Table Lookup (表格查询)]
        LLM -->|询问用户| UserAsk[询问用户]
    end
    
    ToolExec --> Result[执行结果]
    KnowledgeTool --> Result
    TableTool --> Result
    Result -->|更新上下文| Dispatcher
    Result --> Final[输出给用户]
```

### 2.2 核心模块说明

- **[classifier.py](/AI/PicoAgent/backend/src/agents/classifier.py)**: 意图分类器。负责识别用户意图并匹配最合适的 SOP。
- **[dispatcher.py](/AI/PicoAgent/backend/src/agents/dispatcher.py)**: 核心调度引擎。根据 SOP 步骤控制执行流，决定是直接运行工具还是调用 LLM。
- **[sop_loader.py](/AI/PicoAgent/backend/src/core/sop_loader.py)**: 智能加载器。将 Markdown 格式的 SOP 转换为结构化步骤，并利用 LLM 提取关键约束和输入要求。
- **[llm.py](/AI/PicoAgent/backend/src/core/llm.py)**: LLM 客户端封装。默认集成 **NVIDIA API** (提供 Nemotron, DeepSeek, Kimi 等模型支持)，支持多模型切换和双语处理。
- **[memory.py](/AI/PicoAgent/backend/src/core/memory.py)**: 上下文与记忆管理。分层存储全局上下文、步骤历史和工作记忆。

---

## 3. 功能亮点 (Features)

1.  **SOP确定性执行**: 自然语言描述的主观经验库，确保强执行力。
2.  **SLM低耗小模型**: 仅需5B以下的小模型即可。
3.  **地理世界模型**: 提供面向三维世界的交互模型。

---

## 4. 开发路线图 (Roadmap)

### 已实现 (v0.01)
- [x] 混合架构基础框架 (Rules + LLM)
- [x] SOP 智能解析与 Markdown 加载
- [x] NVIDIA API 多模型集成 (默认)
- [x] 基础工具集：计算器、表格查询、知识检索
- [x] 专业 GIS 断面计算工具
- [x] 工具描述与代码注释中文化

### 短期目标 (v0.2 - v0.5)
- [ ] **Web 交互界面**: 基于 FastAPI + React 的现代化控制台。
- [ ] **图形化 SOP 编辑器**: 拖拽式流程设计。
- [ ] **多源知识库**: 支持 PDF/Word 自动解析。
- [ ] **执行日志可视化**: 实时追踪 Agent 决策链路。

### 长期愿景 (v1.0+)
- [ ] **自动 SOP 生成**: 根据历史成功案例自动提炼作业程序。
- [ ] **数字孪生集成**: 与 GeoWorld 实时数据流打通。
- [ ] **行业生态建设**: 覆盖航道设计、水利、土木等更多垂直领域。

---

## 5. 项目结构 (Project Structure)

```text
PicoAgent/
├── backend/                # 后端核心
│   ├── src/
│   │   ├── agents/         # classifier.py, dispatcher.py
│   │   ├── core/           # llm.py, memory.py, sop_loader.py
│   │   └── tools/          # base.py, general_tools.py, gis_tools.py
│   ├── sops/               # SOP 文档库 (*.md)
│   └── knowledge/          # 行业规范与知识库
├── tests/                  # 测试用例
├── .env                    # 环境配置 (含 NVIDIA API Key)
└── README.md               # 本文档
```

---

## 6. 快速开始 (Quick Start)

1.  **配置环境**: 在 `.env` 中设置 `NVIDIA_API_KEY`。
2.  **加载 SOP**:
    ```python
    from src.core.sop_loader import SopLoader
    loader = SopLoader("backend/sops")
    sops = loader.load_all()
    ```
3.  **执行意图**:
    ```python
    from src.agents.classifier import IntentClassifier
    from src.agents.dispatcher import Dispatcher
    
    # 1. 识别意图
    classifier = IntentClassifier(sops)
    sop, params = classifier.route("我想计算断面工程量")
    
    # 2. 调度执行
    dispatcher = Dispatcher()
    result = dispatcher.run(sop, params)
    ```

---
*PicoAgent - 让 AI 成为最靠谱的工程助手。*
