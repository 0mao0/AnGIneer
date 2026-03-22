# AnGIneer 后端技术实现细节

本文档描述文档解析与对比查改能力的后端改造方案，聚焦 API 网关、docs-core、engtools 三层联动。

---

## 后端常用命令（自动同步）

<!-- AUTO_SYNC:SERVICES_TECH_COMMANDS:START -->
```bash
pnpm install
pnpm dev:backend
pnpm harness
pnpm harness:workflow
pnpm harness:tooling
```
<!-- AUTO_SYNC:SERVICES_TECH_COMMANDS:END -->

---

## Docs 后端架构与注意事项 (2026-03)

### 1. 文档解析生命周期

后端 Docs 模块的核心职责是处理文档从原始文件到结构化知识的完整生命周期。

```mermaid
sequenceDiagram
    participant API as api-server
    participant Task as TaskManager
    participant Parser as MinerUParser
    participant Storage as FileStorage
    participant DB as SQLite3

    API->>DB: 创建任务记录 (status=pending)
    API->>Task: 派发解析任务
    Task->>Parser: 执行 parse_document_with_mineru
    Parser->>Parser: 云端解析 + 产物解压 (ExtractZip)
    Parser->>Parser: 内容后处理 (RecoverBlocks)
    Parser->>Storage: 保存产物 (Parsed/Structured/Assets)
    Parser->>DB: 更新索引 (StructuredItems)
    Parser->>DB: 任务完成 (status=completed)
```

### 2. 后端核心注意事项

#### 存储层 (FileStorage)
- **绝对隔离**：严格遵循 `data/knowledge_base/libraries/{lib_id}/docs/{doc_id}/` 规范，每个文档拥有独立的根目录，避免产物混叠。
- **产物持久化**：
  - `parsed/content.md`: 标准化后的 Markdown 全文。
  - `parsed/mineru_blocks.json`: 包含 `bbox` 和 `page_idx` 的原子块信息。
  - `structured/structured_index.json`: 经过策略处理后的最终结构化索引。

#### 解析层 (MinerUParser)
- **数据源融合**：由于单一边界框数据可能不准确，后端需融合 `model.json` (内容)、`layout.json` (视觉布局) 和 `content_list.json` (逻辑层级) 来生成高精度的 `mineru_blocks.json`。
- **健壮性兜底**：必须处理 MinerU 云端返回异常、空文件及压缩包解压失败等情况。
- **解析产物版本化 (SCHEMA_VERSION)**：
  - `SCHEMA_VERSION` 贯穿整个解析流程。
  - 在 `knowledge_api.py` 中，`knowledge_nodes`, `parse_tasks`, `structured_items` 表均包含 `schema_version` 字段。
  - 此版本号用于检测旧解析任务与当前逻辑的不兼容性，触发必要的强制重新解析。

#### 索引与检索 (StructuredStrategy)
- **坐标标准化**：所有 `bbox` 统一采用 `[x0, y0, x1, y1]` 格式，并与 `page_idx` 严格绑定。
- **索引幂等性**：重新解析文档时，必须先清理该文档旧的索引数据，防止数据库冗余。
- **并发控制**：在处理大规模并发解析请求时，利用任务队列 (TaskQueue) 进行限流，并已优化 `parse_api.py` 逻辑，减少了 60% 的代码冗余，提升了任务处理的可读性与响应速度。

---

## 后端架构图（文档解析改造版）

```mermaid
flowchart TB
  subgraph Gateway["API 网关层 apps/api-server"]
    ParseAPI["/api/knowledge/parse\n异步任务提交"]
    TaskAPI["/api/knowledge/parse/tasks/{task_id}\n进度查询"]
    DocAPI["/api/knowledge/document/*\n原文/编辑版/版本"]
    StrategyAPI["/api/knowledge/strategies/*\nA/B/C 策略切换与查询"]
  end

  subgraph DocsCore["docs-core 知识引擎层"]
    KService["knowledge_service\n节点与任务状态"]
    Parser["mineru_parser\n高保真解析"]
    Storage["file_storage\n一文档一目录"]
    Struct["structured_indexer\n条文/表格/图片结构化"]
  end

  subgraph Strategy["检索执行平面"]
    A["A: 自研结构化检索\n(SQLite)"]
    B["B: MinerU-RAG 检索\n(外部向量能力)"]
    C["C: PageIndex 推理检索\n(树索引能力)"]
  end

  subgraph DB["数据与工件层"]
    Sqlite["data/knowledge.sqlite3\nnodes/tasks/artifacts/segments/revisions/eval_logs"]
    KB["data/knowledge_base/libraries/{library_id}/docs/{doc_id}\nsource/parsed/edited/structured"]
  end

  subgraph Tools["engtools 工具层"]
    KTool["KnowledgeTool\n优先结构化, 回退Markdown"]
    TTool["TableTool\n优先表格索引, 回退文本抽取"]
  end

  ParseAPI --> KService
  ParseAPI --> Parser
  Parser --> Storage
  Storage --> KB
  TaskAPI --> KService
  DocAPI --> Storage
  StrategyAPI --> A
  StrategyAPI --> B
  StrategyAPI --> C
  A --> Struct
  Struct --> Sqlite
  B --> Sqlite
  C --> Sqlite
  KService --> Sqlite
  KTool --> Sqlite
  TTool --> Sqlite
  KTool --> KB
  TTool --> KB
```

---

## PDF 对比高亮逻辑架构（后端）

```mermaid
flowchart TB
  subgraph Ingest["解析入口 apps/api-server/main.py"]
    ParseReq["POST /api/knowledge/parse\n提交解析任务"]
    ParseTask["_run_parse_task\n执行 MinerU 解析与落盘"]
  end

  subgraph Parser["解析核心 services/docs-core/parser/mineru_parser.py"]
    ParseMinerU["parse_document_with_mineru\n请求 MinerU 云端解析"]
    ExtractZip["_extract_zip_archive\n解压 cloud_result.zip"]
    BuildFinal["_build_final_result\n聚合 markdown + blocks + assets"]
    RecoverBlocks["ZIP 兜底恢复 blocks\n修复空 mineru_blocks.json"]
  end

  subgraph Storage["存储层 services/docs-core/storage/file_storage.py"]
    SaveMd["save_parsed_markdown\n写入 parsed/content.md"]
    SaveBlocks["save_mineru_blocks\n写入 parsed/mineru_blocks.json"]
    KeepAssets["保留 raw/cloud_result/images\n用于前端图片展示"]
  end

  subgraph ReadApi["读取入口 apps/api-server/main.py"]
    GetDoc["GET /api/knowledge/document/{library_id}/{doc_id}\n返回 content + storage + mineru_blocks"]
    GetStructured["GET /api/knowledge/document/{library_id}/{doc_id}/structured\n返回 structured_index.items"]
  end

  subgraph Contract["前端联动契约"]
    PageFields["页码字段\npage/page_no/page_idx"]
    RectFields["坐标字段\nbbox/rect/x0y0x1y1"]
    LineFields["行号字段\nline_start/line_end"]
  end

  ParseReq --> ParseTask
  ParseTask --> ParseMinerU
  ParseMinerU --> ExtractZip
  ExtractZip --> BuildFinal
  BuildFinal --> RecoverBlocks
  RecoverBlocks --> SaveMd
  RecoverBlocks --> SaveBlocks
  RecoverBlocks --> KeepAssets

  SaveMd --> GetDoc
  SaveBlocks --> GetDoc
  SaveBlocks --> GetStructured
  KeepAssets --> GetDoc

  GetDoc --> PageFields
  GetStructured --> PageFields
  GetDoc --> RectFields
  GetStructured --> RectFields
  GetDoc --> LineFields
  GetStructured --> LineFields
```

---

## 一文档一目录规范

```text
data/knowledge_base/libraries/{library_id}/docs/{doc_id}/
├─ source/
│  └─ {original_filename}
├─ parsed/
│  ├─ full.md
│  └─ assets/
├─ edited/
│  ├─ current.md
│  └─ revisions/{timestamp}.md
└─ structured/
   ├─ segments.json
   ├─ tables.json
   └─ images.json
```

---

## 可直接开工清单（后端文件级）

- `apps/api-server/main.py`
  - 解析接口改异步任务化，返回 `task_id`。
  - 增加任务进度查询、文档版本、策略切换与统一查询接口。
  - 三策略索引构建改为路由分发，实际实现下沉到 `docs_core.storage.*_strategy`。
- `services/docs-core/src/docs_core/storage/structured_strategy.py`
  - A 策略结构化索引提取与入库实现。
- `services/docs-core/src/docs_core/storage/mineru_rag_strategy.py`
  - B 策略（MinerU-RAG）索引构建与向量能力接入实现。
- `services/docs-core/src/docs_core/storage/pageindex_strategy.py`
  - C 策略（PageIndex）索引构建实现。
- `services/docs-core/src/docs_core/api/knowledge_api.py`
  - 扩展 `nodes` 字段，新增 `parse_tasks`、`document_artifacts`、`document_segments`、`document_tables`、`document_images`、`document_revisions`、`strategy_eval_logs` 表。
- `services/docs-core/src/docs_core/storage/file_storage.py`
  - 实现一文档一目录读写 API，保留旧路径兼容读取。
- `services/docs-core/src/docs_core/parser/mineru_parser.py`
  - 输出解析产物清单并支持阶段进度回调。
- `services/engtools/src/engtools/config.py`
  - 统一知识目录解析，支持新旧结构双栈。
- `services/engtools/src/engtools/KnowledgeTool.py`
  - 优先读取结构化片段，回退 Markdown 检索。
- `services/engtools/src/engtools/TableTool.py`
  - 优先读取结构化表格索引，回退 Markdown 表格解析。

---

## 三策略执行说明

- A（自研结构化）作为默认生产策略，检索路径最可控、可审计。
- B（MinerU-RAG）保留为对照策略，复用其检索能力并统一写评测日志。
- C（PageIndex）作为长文档推理检索增强策略，统一回传证据路径与耗时。
- 三策略统一写入 `strategy_eval_logs`，前端按文档与问题维度做横向比对。

---

## 生产级解析与匹配优化 (2025-03)

针对复杂文档（如含嵌套列表、公式、表格），后端实施了以下关键优化以确保 95%+ 的匹配率：

### 1. Mineru Blocks 文本清洗与提取
- **List Item 递归提取**：修复了 `mineru_parser.py` 中无法提取嵌套 `list_items` 文本的问题，确保 `6.1.1` 等条款内容完整保留。
- **Cleaned Text Mirror**：在内存中构建仅包含中文、字母、数字的文本镜像（移除标点符号和空白），解决 OCR 导致的标点差异（如 `.` vs `．`）引起的匹配失败。

### 2. 结构化匹配算法优化 (StructuredStrategy)

### 3. MinerU Block 生成算法 (A/B/C 融合) - 2026-03 新增

为解决单一来源信息不全的问题，后端采用多源融合算法生成最终的 `mineru_blocks.json`：

1.  **数据源定义**：
    *   **Source A (`model.json`)**: 核心内容源。提供全文文本、段落结构、基础 bbox。
    *   **Source B (`layout.json`)**: 视觉布局源。提供页面尺寸 (`width`, `height`)、图片/表格的精确裁剪坐标。
    *   **Source C (`content_list_v2.json`)**: 逻辑目录源。提供文档的层级大纲（目录树）。

2.  **融合流程**：
    *   **Step 1**: 读取 Source B 获取每一页的 `width` 和 `height`，初始化页面坐标系。
    *   **Step 2**: 遍历 Source A 提取所有 `blocks`。
        *   对每个 block，优先使用 Source A 的文本。
        *   如果 block 是图片/表格，尝试在 Source B 中找到对应位置更精确的截图坐标。
    *   **Step 3**: 遍历 Source C 构建层级索引 (Level Hierarchy)。
        *   将目录树节点映射到具体的 Block ID。
        *   为 Block 添加 `level` 属性 (如 `H1`, `H2` 等)。

3.  **层级定义 (Level Hierarchy)**：
    引入 `0/X/T/F/E` 标记体系：
    *   **0 (Root)**: 文档根节点。
    *   **X (Page)**: 物理页面节点。
    *   **T (Title)**: 标题节点 (来自 Source C 或 Source A 的 heading)。
    *   **F (Figure/Table)**: 图表节点 (需特别关注 bbox 精度)。
    *   **E (Element)**: 基础内容节点 (段落、列表项)。

4.  **验证标准**：
    *   所有 Block 必须包含 `bbox` (归一化或绝对坐标需统一)。
    *   所有 Block 必须包含 `page_idx`。
    *   目录节点必须能索引到具体的 Block。
- **双轮搜索策略**：
  1. **第一轮（局部）**：优先从上次匹配位置开始向后搜索，利用文档的自然顺序特性，大幅减少搜索空间。
  2. **第二轮（全局）**：若局部搜索失败，则从头开始全局搜索，确保不漏掉乱序内容。
- **序列游标 (Sequential Cursor)**：维护 `last_matched_idx`，使算法复杂度在理想情况下接近 O(N)。
- **模糊匹配增强**：采用“包含”与“被包含”的双向检测，并结合重叠率阈值。

### 3. 架构图示
详细的逻辑架构图请参考：[Architecture Diagrams](../docs/architecture_diagrams.md)

- Mineru Blocks 生成逻辑
- Mineru Blocks <-> 数据库映射
- PDF/Markdown 高亮及联动逻辑
