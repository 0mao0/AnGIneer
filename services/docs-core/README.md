# angineer-docs-core

[![PyPI](https://img.shields.io/pypi/v/angineer-docs-core)](https://pypi.org/project/angineer-docs-core/)

AnGIneer 的文档解析入库引擎（纯 Python 库）：把工程规范 / PDF / Office 文档跑成
「**可读、可查、可算、可引用**」的知识库数据——一条管线覆盖
**源文件准备 → 格式转换 → MinerU 解析 → PoPo 强化 → 结构化 → 图描述 → SQLite+FTS → 向量索引 → 知识图谱**，
外加五路检索、text2sql 与产物导出。

| 能力 | 说明 | 靠什么 |
| :--- | :--- | :--- |
| 📖 可读 | 高保真解析 PDF，保留结构、公式、图表 | MinerU 端点（HTTP） |
| 🔍 可查 | 语义检索 + 表格精确查询 + 条款定位（五路召回 + 重排） | canonical 七表 + qdrant |
| 🧮 可算 | 公式语义、表格插值、条款计算（供上层工具消费） | 结构化的 canonical 产物 |
| 📎 可引用 | 条文 / 表格 / 图片的块级溯源 | `citation_targets` + 块 id |

> 定位：只做**数据面**（解析 / 建索引 / 图谱 / 检索），**不含 HTTP 服务与前端**。
> 大算力全部在外部服务：版面解析、视觉结构强化、图描述、embedding、rerank 都走 HTTP 端点（配置见下）。

## 管线（9 个阶段 + 导出）

`hard` = 失败即中止；`soft` = 失败降级继续并在 `parse_stages` 留痕。

| # | 阶段 key | 名称 | 类型 | 依赖 | 做什么 |
| :-- | :--- | :--- | :--- | :--- | :--- |
| 1 | `source_prep` | 源文件准备 | hard | — | 落地源文件、登记文档节点、准备解析输入 |
| 2 | `convert` | 格式转换 | hard | source_prep | 非 PDF（doc/docx/xls…）经 LibreOffice 转 PDF |
| 3 | `raw_parse` | MinerU 解析 | hard | convert | 调 MinerU 端点（file_parse ZIP 协议），产出 markdown / 图片 / `middle.json` |
| 4 | `popo` | PoPo 强化 | **soft** | raw_parse | PoPo 做视觉结构强化，产出 enriched blocks（需 VLM 端点） |
| 5 | `structure` | 结构化 | hard | raw_parse | **Solo 是唯一构建者**；PoPo 信号只作为增强注入（对齐 / 合并 / 层级融合 / 续表） |
| 6 | `figure_describe` | 图描述 | soft | structure | VLM 描述图表内容（可关） |
| 7 | `fts` | SQLite + FTS | hard | structure | canonical 七表 + 全文索引（检索数据面） |
| 8 | `vectors` | 向量索引 | soft | fts | qdrant（默认）/ sqlite / chroma |
| 9 | `graph` | 知识图谱 | soft | structure | 实体与关系抽取入库 |

第 10 步是产物导出（`step10_export`：按册导 markdown / 图片 / 索引 / 图谱）。

## 安装

```bash
pip install angineer-docs-core
# 或钉版本
pip install "angineer-docs-core @ git+https://github.com/0mao0/angineer-docs-core.git@v0.1.0"
```

Python 要求 `>=3.10`。运行依赖：`angineer-tree-core`（树表底座）、`angineer-ai-inference`（LLM 客户端）、
`pydantic>=2`、`PyMuPDF`、`numpy`、`python-dateutil`、`qdrant-client`、`requests`、`python-dotenv`。
可选 extras：`[chroma]`（旧向量后端）、`[text2sql]`（领域关键词 YAML）。

## 另有外部依赖（不随包提供）

| 依赖 | 用途 | 怎么配 |
| :--- | :--- | :--- |
| MinerU 端点 | 版面解析（GPU 大头） | `MINERU_CONFIGS` |
| PoPo 端点 | 视觉结构强化 | `POPO_CONFIGS` |
| 图描述端点 | 图表描述 | `FIGURE_DESCRIBE_CONFIGS` |
| embedding 端点 | 向量化 | `EMBEDDING_CONFIGS` |
| rerank 端点 | 重排 | `RERANKER_CONFIGS` |
| Qdrant | 向量库（默认 provider） | `QDRANT_URL`（也可换 sqlite / chroma） |
| LibreOffice | 非 PDF → PDF | 系统安装，`LIBREOFFICE_BIN` 或 PATH |

## 快速开始

```python
import os

os.environ["KNOWLEDGE_BASE_DIR"] = "/srv/knowledge"          # 数据根（也可用 ANGINEER_DATA_ROOT）
os.environ["MINERU_CONFIGS"] = '[{"name":"dgx","url":"https://your-gateway/api/mineru","api_key":"..."}]'
os.environ["POPO_CONFIGS"]   = '[{"name":"dgx","url":"https://your-gateway/api/popo/v1","api_key":"...","model":"Popo"}]'
os.environ["DOCS_VECTORSTORE_PROVIDER"] = "qdrant"
os.environ["QDRANT_URL"] = "http://localhost:6333"

from docs_core.parse_pipeline import ParseOrchestrator

orch = ParseOrchestrator()                                             # 不注入时用包内置的解析记录表
doc_id = orch.ensure_document("default", "/abs/path/spec.pdf")         # 登记文档节点
task = orch.create_parse_task("default", doc_id, "/abs/path/spec.pdf") # 后台线程跑全链
print(task["task_id"])

orch.get_parse_task(task["task_id"])     # 查进度 / 当前阶段
orch.cancel_parse_task(task["task_id"])  # 协作式取消
orch.retry_parse_task(doc_id)            # 失败重跑
```

- 阶段级重跑与校验：`STAGE_REGISTRY` / `resolve_stage_order` / `validate_stage_retry` / `compute_resume_stages`；
- 检索侧入口：`docs_core.step09_query`（五路召回 + 重排 + text2sql）；
- 知识库与节点管理：`docs_core.get_docs_service()` / `DocsService`。

## 配置（常用）

| 变量 | 默认 | 说明 |
| :--- | :--- | :--- |
| `KNOWLEDGE_BASE_DIR` | — | **数据根（最高优先）**：元库 / 索引 / 图谱 / 文档目录都挂它下面 |
| `ANGINEER_DATA_ROOT` | — | 数据根（次优先，取 `<root>/knowledge`） |
| `ANGINEER_REPO_ROOT` | 仓库标记探测 | 仓库树根。独立安装（wheel）里没有仓库树，需要数据根请显式给上面两个之一 |
| `MINERU_CONFIGS` / `POPO_CONFIGS` / `FIGURE_DESCRIBE_CONFIGS` / `EMBEDDING_CONFIGS` / `RERANKER_CONFIGS` | — | JSON 数组，顺序=优先级，第一项为默认；连接失败/超时自动切下一项 |
| `DOCS_VECTORSTORE_PROVIDER` | —（必填） | `qdrant` / `sqlite` / `chroma`；不设会直接报错（防静默连空库） |
| `QDRANT_URL` | — | `provider=qdrant` 时必填 |
| `LIBREOFFICE_BIN` | PATH 探测 | `soffice` 路径（非 PDF 输入必需） |
| `POPO_MAX_CONCURRENCY` | 4 | PoPo 强化的并发闸（FIFO 排队） |
| `FIGURE_DESCRIBE_ENABLED` | 见 `.env.example` | 图描述开关 |

## 包里包含什么

- **`docs_core`**：管线与数据面本体（9 阶段、canonical 存储、五路检索、图谱、导出）；
- **`popo`**：PoPo fork（上游 MinerU-Popo 的定制版）随包发布，两个要点：
  - 它是**顶层导入名 `popo`**（上游没有 `__init__.py`，按命名空间包收集），装完 site-packages 里会多出这个目录；
  - 缺失也不报错——第 4 步按「软阶段」跳过，结构由 Solo 单独构建（质量降级、链路不断）。
    自定义位置可用 `POPO_REPO_PATH` 指定。
- 依赖 **`angineer-tree-core`** 与 **`angineer-ai-inference`**，pip 会自动带上。

## 目录结构

```text
services/docs-core/
├── src/
│   ├── docs_core/
│   │   ├── paths.py                 # 布局：数据根 + 文档目录（纯路径计算，无 IO 副作用）
│   │   ├── docs_service.py          # 门面：知识库/节点/任务落库与查询的统一入口
│   │   ├── parse_pipeline.py        # 阶段注册 / 顺序 / 状态机 / 编排器
│   │   ├── models/                  # 全管线共享契约（canonical 七表类型等）
│   │   ├── step01_source_prep/      # 源文件准备
│   │   ├── step02_convert2pdf/      # LibreOffice 转 PDF
│   │   ├── step03_mineru_parse/     # MinerU 解析 + PoPo 强化（popo_enhance）
│   │   ├── step04_structure/        # Solo 结构构建 + PoPo 信号消费（popo/ 六件套）
│   │   ├── step05_sqlite_fts/       # canonical SQLite + FTS（rebuild / store）
│   │   ├── step06_vectors/          # 向量索引（qdrant / sqlite / chroma + embedding 客户端）
│   │   ├── step07_graph/            # 知识图谱（实体 / 关系 / 证据包）
│   │   ├── step08_maintain/         # 巡检与维护
│   │   ├── step09_query/            # 检索（五路召回）、text2sql、对外协议
│   │   ├── step10_export/           # 产物导出
│   │   └── library_registry.py / parse_records_store.py / kb_migrator.py …
│   └── popo/                        # PoPo fork（本地定制，随包发布；上游同步见 UPSTREAM_SYNC.md）
├── tests/                           # 88 个测试文件 / 500+ 用例
└── pyproject.toml
```

## 不在本库范围

- HTTP / API 服务（由主仓库的 docs-api 实现）、前端与管理台；
- MinerU / PoPo / VLM / embedding / rerank 的推理服务本身；
- 知识库数据的业务展示与权限。

## 开发与测试

```bash
pip install -e ".[dev]"
python -m pytest tests -q
```

独立环境（无仓库树、无 `.env`）也能跑：`tests/conftest.py` 会先按 dotenv 规则加载 `.env`（若有），
再补缺省 —— 向量后端用 `sqlite`、数据根指向临时目录；跨服务用例（需要 docs-api）自动跳过。
当前基线：**507 passed, 17 skipped**（无外部服务、无网络）。

## 许可

MIT
