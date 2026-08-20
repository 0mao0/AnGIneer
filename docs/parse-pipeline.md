# AnGIneer 一体化文档解析管线（Parse Pipeline）技术说明

> 从源文件（PDF/DOCX/PPTX/XLSX）到结构化知识库的一体化解析管线（核心 8 阶段），以及断点恢复、
> GPU 槽位、产物校验与踩坑记录。核心代码在 `services/docs-core/src/docs_core/`。

## 1. 8 阶段注册表

`parse_pipeline.py::STAGE_REGISTRY`：

| key | 显示序号 | 名称 | 性质 |
| :--- | :--- | :--- | :--- |
| `source_prep` | 1 | 源文件准备 | hard |
| `convert` | 2 | 格式转换（LibreOffice → PDF） | hard |
| `raw_parse` | 3.1 | MinerU 解析 | hard |
| `popo` | 3.2 | PoPo 强化（LLM） | soft |
| `structure` | 4 | 结构化（Solo 唯一构建者） | hard |
| `fts` | 5 | SQLite+FTS | hard |
| `vectors` | 6 | 向量索引 | hard |
| `graph` | 7 | 知识图谱 | hard |

- hard：必须成功；soft：失败不阻塞整体（如 PoPo 强化失败仍保留核心产物）；
- 显示序号与后端 `step` 一致（3.1/3.2 同属第 3 步）；
- 单阶段可单独重跑（`/documents/{doc_id}/stages/{stage}/retry`）。

## 2. 数据流转与产物

```text
source/           原始文件
  └─ convert → PDF（LibreOffice）
       └─ raw_parse → MinerU
            ├─ parsed/content.md
            ├─ parsed/mineru_raw/{content_list,model,middle,origin.zip}
            ├─ parsed/images/
            └─ parsed/popo/{enriched_blocks.json, document_tree.json}
                 └─ structure → parsed/doc_blocks_graph.jsonl + doc_blocks_graph_meta.json
                      └─ fts / vectors / graph 索引
```

每份文档一个目录：`data/knowledge_base/libraries/{library_id}/documents/{doc_id}/`。

### 2.1 内部 IR 产物

- `ir.json`：由 doc_blocks_graph.jsonl + meta 映射生成的内部适配 IR（非跨系统交付物）；
- `raw/doc_blocks_graph.jsonl` 与 `raw/doc_blocks_graph_meta.json`：AnGIneer 原始产物留档，供溯源/调试；
- `content.md`：阅读与 LLM 语义层使用的 Markdown。

### 2.2 产物校验

- `AnGineerIrMapper` 把 graph/meta 映射为 IR，校验不合法直接拒收并报原因；
- OCR 低置信度比例（`OcrLowConfidenceRatio`）用于质量标记；
- 缺失 `doc_blocks_graph.jsonl` / `meta` 视为失败。

## 3. GPU 槽位与并发

- `MinerU 任务占用的 GPU 槽位`按提交序号先来先服务，进入 raw_parse 前获取；
- 取消任务会让位给下一个排队任务，避免 GPU 空转；
- `PoPo 4B 推理（远端 vLLM）槽位`同样按提交序号先来先服务（`POPO_MAX_CONCURRENCY`，默认 1），
  防止多个文档并发把远端 vLLM 打满；推理瞬时失败（超时/连接类）按
  `POPO_INFERENCE_RETRIES`（默认 1）退避重试，仍失败才回滚并走 solo 兜底；
- 批量解析（`ParseDocumentsJob`）并发提交，写库串行（EF Core DbContext 非线程安全，DredgeAI 侧同样约束）。

## 4. 断点恢复与重试

### 4.1 单文档重试

- 失败文档可单独重新解析（`ParseDocumentJob`）；
- 复用 AnGIneer 侧 `doc_id`：processing/failed 先查状态，能 resume 则 resume；
- 404/403（doc_id 不存在或不属于当前 API Key）→ 重新上传；
- 恢复时计算剩余阶段（`resume_stages.py`），已完成阶段保留。

### 4.2 状态推进（ParseTaskStateAdvancer）

- 全部文档落定后推进任务状态；
- 有失败文档 → partial；全部失败 → failed（不静默降级）；
- 上传招标文件且未锁定条款快照 → 等待条款确认（DredgeAI 比标场景）；
- 重解析后不自动重跑全量对比，由用户显式触发（v2 §5.3）。

## 5. 结构化（structure 阶段）

- **Solo 是唯一构建者**：由 raw_parse 产物构建结构（块角色、层级推断）；
- PoPo 只做增强（label 对齐、符号标注、表格/公式 enrich、合并仲裁），不参与结构构建；
- 块角色与层级规则见 `docs/block-role-hierarchy-design.md`、`docs/front-matter-role-group-design.md`；
- 跨页表格/续表按"纯附录/跨页表格兜底"的状态机处理。

## 6. 索引入库

- `canonical_*`：文档/页/块/大纲/表格/引用目标规范化；
- `document_segments` / `doc_blocks`：结构化索引条目；
- `canonical_chunk_fts`：SQLite FTS5 全文索引；
- `canonical_vectors`：向量索引（SQLite/Chroma，按 `DOCS_VECTORSTORE_PROVIDER` 切换）；
- 重新解析必须先清理该文档旧索引，保证幂等。

## 7. 关键踩坑记录

| 问题 | 现象 | 对策 |
| :--- | :--- | :--- |
| 先写 meta 后盖 md | build_id 瞬时不一致 | 前端短重试 3 次再判 mismatch，禁用高亮 |
| staging 目录残留 | 并发/中断产物混乱 | `parsed.staging-*` 目录原子替换 |
| LibreOffice 转换超时 | convert 挂死 | 超时与取消让位 |
| OCR 低置信 | 文本错乱 | 记录 OcrLowConfidenceRatio，前端提示 |
| stale processing 记录 | 任务卡在解析中 | 启动自愈 + resume；进度=0 空阶段消息视为陈旧 |
| 重解析不续跑对比 | 结果不一致 | v2 §5.3 显式"重新对比" |

## 8. 关键代码锚点

- 管线：`parse_pipeline.py`（STAGE_REGISTRY / resolve_stage_order / 单阶段执行）
- 阶段实现：`step01_source_prep` ~ `step08_maintain`
- 后台任务：`docs-api/parse_orchestrator`、`resume_stages.py`、`startup_recovery.py`
- PoPo：`step03_mineru_parse/popo_enhance.py`、`popo/`（子模块，环境变量定制见 AGENTS.md）
- 外部 v1 API：`services/docs-api/routes/v1/documents.py`
- 产物导出：`step10_export/export_artifacts.py`
