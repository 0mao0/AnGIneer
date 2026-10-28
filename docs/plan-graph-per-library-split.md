# 施工单：图谱存储改「一库一文件」（graph-per-library-split）

**日期：** 2026-10-28（用户拍板 A 方案，见 [remaining-kb-package.md](remaining-kb-package.md) §10 出路讨论）
**目标：** `knowledge/graph.sqlite` 全局单文件 → `knowledge/libraries/<lib>/graph.sqlite` 每库一文件，与 index.sqlite 同构。导入冲突闸随之删除实体比对，跨环境导入带图谱语料包不再被拦。

## 1. 背景与依据（2026-10-28 实测）

- 图谱逻辑层**早已按库隔离**：全部表带 `library_id` 列、`UNIQUE(name, library_id)`、按库删除/索引；读侧（图谱页签、agent 图谱检索）全部带库参数。物理单文件是唯一的全局点。
- 生产现状：3,496 实体（default 1399 / lib-261558be 2070 / lib-7582b086 27），跨库关系仅 **16 条**；全局文件另有历史悬空行（P1-7 实采 436 条，切片忠实镜像口径保留）。
- relations 等引用表有 `REFERENCES graph_entities(entity_id)` 真 FK ⇒ 拆分/迁移必须保证端点实体同文件在场。

## 2. 目标形态

| 项 | 改后 |
|---|---|
| 路径 | `paths.resolve_library_graph_db_path(library_id)` = `library_root(lib)/graph.sqlite` |
| 全局文件 | 仅作迁移源；拆分后改名 `graph.sqlite.migrated-<ts>` 留档，不再被业务读写 |
| 导入 apply | 图谱阶段 = 包内 `graph/graph.sqlite` **整文件落位**到库目录（原 `_merge_graph` 全局合并删除） |
| 导入冲突闸 | 删除 `package_entities/target_entities` 比对与「首版阻断」分支；library_id/节点 id/collection/index 闸保留 |
| 导出切片 | `build_library_graph_slice` 退化为整文件拷贝（本库文件本就只含本库行） |
| 跨库共享 | 终止：同名实体按库各自成行（与 `UNIQUE(name, library_id)` 语义一致）；拆分时 16 条跨库关系留在关系自身 library 文件、异库端点实体随行拷贝保 FK |

## 3. 调用点改造清单（grep 实采）

| 文件 | 现状 | 改法 |
|---|---|---|
| `paths.py:89` | `resolve_graph_db_path()` 全局 | 新增 `resolve_library_graph_db_path(lib)`；旧函数保留仅供迁移与回退 |
| `server/app.py:169` entity_search_internal | 全局 store | 按 `request.library_id` 取库文件 |
| `retrieve_routes.py:84,128` | 全局 store | 同上（调用方带 library_id） |
| `docs_routes.py:1710` | 全局 | 按上下文库 id |
| `docs_service.py:524 _delete_document_graph_data` | 全局按 doc 删 | 签名加 library_id，取库文件 |
| `library_delete.py:378 _delete_graph` | 全局按行删 | 删库文件整文件（目录删除兜底已有） |
| `kb_migrator.py`（拆并） | `GraphStore.move_doc_graph` 单文件内搬 | 改跨文件搬：源文件读→目标文件插（library_id 改标）→源文件删 |
| `push_to_graph.py:40`（解析写侧） | 全局 | 解析阶段已知 library_id，取库文件 |
| `step09_query/agent_port.py:413 entity_local_search` | `db_path or 全局` | 缺省改按 `library_id` 解析；`db_path` 注入参数保留 |
| `agent_tools.py:1363`（angineer-core） | 显式传 `db_path=graph_db` | 不再传全局 db_path（port 内按库解析），改动态最小 |
| `graph_routes.py _get_store`/`/stats`/`/entities` | 全局 | `/stats`、`/entities` 聚合遍历各库文件；其余端点按库 |
| `step08_maintain/config.py:105` + `runner._connect_graph_db` | 单文件 env/硬编码 | config 去 `graph_db_path` 单值语义，runner 改经 facade 按需取文件；去重检查/统计遍历各库 |
| `aichat-api/dream_cycle_routes.py:116,181,215` | `cfg.graph_db_path` 直连 + 按 entity_id 操作 | 经 facade「按 entity_id 找所在库文件」（遍历各库文件定位） |
| `export_artifacts.py:170` | 全局 `_has_rows` | 按库文件 |
| `routes/v1/documents.py`（按文档导出 graph sqlite） | 全局过滤 | 按库文件过滤 |
| `corpus_import_apply.py:585,620,638` + `_merge_graph` | 实体闸 + 全局合并 | 闸删实体比对；apply 图谱阶段改整文件落位；`_merge_graph` 删除 |
| `corpus_package.py check_conflict_gate` | 实体参数 + warnings | 删实体参数与 warnings 分支 |
| `corpus_slicing.py:189 build_library_graph_slice` | 全局闭包切片 | 整文件拷贝（checkpoint+copy），fk_violations 口径保留 |
| `scripts/kb_corpus_import_cleanup.py:110,211` | 清全局 graph 行 | 改删库文件 |
| `docs-api/main.py` 启动 | — | 新增：启动先跑 `split_global_graph_if_present()`（幂等） |

## 4. 迁移设计（`split_global_graph_if_present`）

- 触发：启动时；条件＝全局 `knowledge/graph.sqlite` 存在且未改名过。
- 步骤：checkpoint 源 → 逐表按行分组写各库新文件（GraphStore 建骨架）→ 联结表 `library_id=''` 行按父实体/父工件归属改标 → 跨库关系留自身 library 文件、异库端点实体随行拷贝 → **逐表行数对账（分文件之和==源）不一致即中止并 raise（不动源文件）** → 全部通过后源文件改名 `graph.sqlite.migrated-<YYYYMMDDHHMM>` 留档。
- 幂等：改名后条件不成立即 no-op；半成品库文件以下一次拆分为准（覆盖重建）。
- 读回退：facade 读路径＝库文件存在则用之，否则回退全局文件（迁移失败时不丢读）。

## 5. 任务分解

| # | 任务 | 验收 |
|---|---|---|
| T1 | paths helper + `graph_files` facade（按库路径/遍历/按实体定位/全局回退）+ 单测 | 新单测绿 |
| T2 | 拆分迁移 + docs-api/main.py 启动钩子 + 单测（双库+跨库关系+空联结行+对账中止+幂等） | 新单测绿；本地旧格式根实拆一次 |
| T3 | 写侧切换：push_to_graph/parse 链、docs_service 删文档、library_delete、retrieve_routes、app.py | 解析一篇出图落到库文件 |
| T4 | 读侧切换：graph_routes（含聚合）、agent_port、agent_tools、step08/dream_cycle、export_artifacts、v1 documents | 图谱页签/图谱检索/维护操作读数正常 |
| T5 | 导入侧：闸删实体检查、apply 图谱整文件落位、对账口径、清理 CLI | 导入 std-municipal 包预检 200、apply 后库文件图谱齐 |
| T6 | 导出侧：切片整文件拷贝 + corpus_package 计数不变 | 导出包含库文件图谱、fk_violations 如实 |
| T7 | 拆并（kb_migrator.move_doc_graph 跨文件化） | 拆并后源/目标库文件图谱行数此消彼长、FK 干净 |
| T8 | 全链冒烟 + 全量 typecheck/test + 文档回写 + commit | 四链（页签/检索/导入/删库）+ 拆并全绿 |

**回滚：** 代码回退 + 把 `graph.sqlite.migrated-*` 改名回 `graph.sqlite`（拆分不删任何数据）。

## 6. 明确不做

- 不改图谱功能本身（抽取/审核/去重逻辑零改动，只动存储定位）；
- 不合并/清理历史悬空行（保持切片镜像口径）；
- angineer-core 独立包只做最小配合（agent_tools 不再传全局 db_path）。

---

## 7. 实施记录（2026-10-28 当日完成）

**落地形态与施工单的差异（均为实施中发现、已按更小改动收敛）：**

1. **导出切片函数零改动**（原计划「退化为整文件拷贝」）：`build_library_graph_slice` 的按 `library_id` 过滤逻辑作用在单库文件上同样正确（闭包 SQL 覆盖跨库拷贝实体），只改调用方优先取库文件、回退全局——省掉一整块重写面。
2. **拆并撞名收敛（D4）跨文件版保源行**：跨文件 FK 无法引用他文件实体，两文件各自持有同名实体（与 `UNIQUE(name, library_id)` 语义一致）；关系重指目标文件行，源行保留。
3. **拆分时空标行归一**：关系/工件行 `library_id=''` 按解析出的归属库写死——导出切片与导入对账都按 `library_id=?` 过滤，空标行会漏。
4. **启动迁移失败不阻断启动**：业务统一走 `resolve_graph_db_for_library`（库文件 > 全局回退），读写同源无分叉窗口。

**验证证据：**

- 单测：`test_unit_graph_files_split`（4）、`test_unit_graph_move_between_files`（4）、导入/切片/拆并相关全套 102 绿；`services/docs-core/tests` 图谱组 + `test_agent_port` 19+17 绿；angineer-core 端口契约除 **1 处既有失败**（relevant_citations limit 默认值，与本次无关）外全绿；全仓 `tests/unit + tests/docs-core` 1091 绿、6 处既有失败（GPU 闸/popo 守卫/users 路由/citations 契约，均不在改动面）。
- **真实数据拆分**：本地 `data/knowledge/graph.sqlite`（7,001 实体 / 182,467 关系 / 18,440 原则 / 9,921 联结）拷副本实拆 → 关系/工件/联结逐表精确相等、实体多出 1,712 条跨库拷贝件（FK 支撑）、唯一悬空＝default 库 436 条（P1-7 记录的历史脏数据，继承合规）、备份 `graph.sqlite.migrated-*` 落盘、幂等二次运行 no-op。
- **CLI 导出→导入闭环**：std-municipal（5 docs/820 chunks/124 关系/84 实体）导出后导入空临时根：图谱文件落 `knowledge/libraries/std-municipal/graph.sqlite`、无全局文件生成、逐表对账与 manifest 一致、FK 零悬空。
- 未做：在线服务冒烟（本地 8790/8791 未运行）；生产拆分发生在下次部署首启（启动钩子自动执行并留备份）。

**运维注意：** 首次部署该版本时启动日志会打印「启动迁移: 图谱按库拆分完成」；回滚＝代码回退 + 把 `graph.sqlite.migrated-*` 改名回 `graph.sqlite`（拆分不删数据）。
