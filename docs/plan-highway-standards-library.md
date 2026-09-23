# 高速养护规范库（简化版记录）

> 状态：**已落地**（2026-09-20）。原「共用层 + 各企业独有层 + catalog 表驱动 + 检索侧多库合并」的复杂方案**已废弃**——
> 它脱离实际：`资料/` 只是原料目录，系统数据本来就在 `data/`（`knowledge_base/`、`parse_records.sqlite`），
> 不需要在系统外再造一套 catalog 与检索设计。

## 现在是什么样

`资料/高速养护/`（gitignored）＝ 高速养护规范的原料目录，一个目录 + 一份清单就够：

| 文件 | 作用 |
|---|---|
| `清单.md` | **目录清单**：模块结构表 + 203 本文件明细 + 22 项缺口（含优先级与来源提示） |
| `_index.tsv` | 机器可读索引（模块 / 标准号 / 名称 / 文件名） |
| `build_from_archive.py` | 从 `资料/正式规范/` 复制并按模块归位；幂等，重跑即刷新清单 |
| `01-养护/` … `09-地方标准/` | 203 本 PDF，按业务模块分 9 个目录（地方标准按浙江 / 其他省市再分） |

来源与规模：`资料/正式规范/` 全量归档（5038 条题录 / 2348 本 PDF）里的「公路主体」层共 203 本 / 1.4 GB。
上游 2690 条「有元数据无附件」的记录中，含「公路」或 `JTG` 的为 0 条，即公路类已收全、无缺口。

归档一份原件、库里一份副本：`资料/正式规范/` 的 PDF 不动（还有 2145 本其他专业件留在那儿）。

## 入库

解析入库走 AnGIneer 既有链路（管理端上传 `/api/knowledge/upload` 或 v1 `/api/v1/documents/parse`），
产物落 `data/knowledge_base/libraries/<lib>/documents/<doc>/source|parsed/`。
本目录只负责「放什么、放哪」，不参与入库。

## 备查：多企业复用时的一个真实约束

将来若多家高养企业共用一套规范语料，会撞上这个点（已核实，非猜测）：

- 一份文档**只能属于一个库**：`nodes.id`、`canonical_documents.doc_id` 均为 PRIMARY KEY，
  且 `library_id NOT NULL`（`services/docs-core/src/docs_core/step05_sqlite_fts/store/blocks_sql_store.py:65`、
  `.../store/canonical_sql_store.py:121-123`）。
- 检索只认单个 `library_id`，文档节点只从该库加载
  （`services/docs-api/retrieve_routes.py:27-40`、`.../step09_query/retrieve_service.py:24-37`）。
- 节点集为空时 `doc_ids` 会退化成不过滤（`.../retrieval/dense_retriever.py:135-136`）→ **有串库风险**。

即"共用规范一份、企业只放独有件、检索时合并两个库"当前做不到，需要改检索侧（小改）或每企业复制一份共用件（解析成本翻倍）。
真要做的时候按这个结论起步，不要再从零论证一遍。
