# 知识库自包含语料包 v2：每库一包（导出切片 + 独立桶导入 + 上传 UI）施工计划

> **For agentic workers:** REQUIRED SUB-SKILL: 用 subagent-driven-development（推荐）或 executing-plans 逐任务执行。步骤用 `- [ ]` 复选框跟踪。

**Goal:** 把语料包从「整组共享 sqlite/qdrant 一个包」升级为 v2 格式：**大 zip 里每库一个小 zip，每个小 zip 自包含该库的全部检索资产**（canonical+FTS 切片、文档树、向量快照、图谱切片），可单库独立交付与导入；导入侧每库独立桶（自己的 sqlite 文件 + 自己的 qdrant collection），归入操作者指定的组；导入通道 = CLI 扩展 + admin-web 上传 UI。**全程零重解析、零重嵌入**：切片全部从现有产物抽取；embed 模型不一致的 v2 包导入**直接阻断**（v2 不支持 reembed——rebuild 工具未覆盖独立桶，要求以目标模型重出包；v1 旧包不在范围，2026-10-18 修订）。

**Architecture:**
```
导出（docs-api 进程内，流式不落盘；CLI 同源）
  选库 → ①组 sqlite ATTACH 抽 12 张 doc 表 + FTS 行 → index/index.sqlite（临时文件）
        ②全局 graph.sqlite 闭包剪裁（本库行 ∪ 关系端点在内的引用实体）→ graph/graph.sqlite（临时文件）
        ③源 collection 按 library_id 过滤 → 临时每库 collection → 原生快照（流）
        ④文档树原样收（排除 mineru_raw/popo）
  → 小 zip（内层，manifest 最后写）= libraries/<lib>.zip
  → 大 zip（外层流式嵌套 + bundle manifest）

导入（CLI / HTTP）
  大 zip 或单个小 zip → 闸：schema / embed / 冲突（library_id、node id、collection 名、落盘路径）/ sha256
  → 应用：files 相对路径放回 → index.sqlite 落 knowledge/libraries/<lib>/index.sqlite
        → graph 切片单事务顺序合并进全局 graph.sqlite → meta 行（nodes/tree_node/libraries）
        → registry 行（改写 sqlite_file/collection/group）→ 快照 recover 成本库 collection
  → 逐表对账 counts + FK 检查 → reload_scope_cache（HTTP）/ 重启提示（CLI）
```

**Tech Stack:** Python 3.11+ / FastAPI（docs-api）/ sqlite（registry.sqlite、组 sqlite、graph.sqlite）/ qdrant v1.19（snapshot + scroll/upsert REST）/ Vue3 + ant-design-vue（admin-web）/ pytest。

**日期:** 2026-10-17。
**执行状态（2026-10-20）：** P1-1～P1-7、P2-0、P2-1 已完成，已随 v0.3.0 发布（origin/main `a8ebf700`）。**P2-2 可恢复；恢复顺序 = P1-8（evals 库根）→ P2-0b（doc_catalog）→ P2-2。**
**业主定版决策（2026-10-17）：** ①按组导出可以，但包内必须是每库一个小 zip；②每库 zip 自包含、不与其他库耦合；③包内必须带图谱；④导入落位=归入指定组、每库独立桶；⑤导入通道=CLI+admin-web 上传 UI；⑥v2 全面替换 v1；**v1 旧包暂无人用，不纳入导入兼容/验收**（2026-10-18 修订）；⑦**v2 不支持 reembed**（模型不一致阻断，文案三处收口，见 P2-4）。
**上游/关联：** `docs/plan-standards-kb-corpus-package.md`（v1 通道，已完结）｜`docs/plan-harvey-enumeration-retrieval.md`（`doc_catalog` / `doc_search`，P2-0b 合流）｜`docs/report-harvey-lab-100-final.md`（保留/未采纳清单）｜`docs/report-harvey-lab-100-qwen38.md`（Qwen3.8 臂）｜`docs/design-kb-export-ui.md`（v1 管理后台导出，本计划完成后改写）｜`services/docs-core/src/docs_core/corpus_package.py`（现导出核心）。

---

## 已核实的代码事实（施工前先信这些，别重新考古）

| # | 事实 | 位置 |
|---|---|---|
| F1 | 库→存储真相源 = `data/registry.sqlite`：`library_registry` 每行有 `sqlite_file`（相对 data 根）与 `collection`，**按库解析**（`resolve_collection` / `resolve_index_db_path`）；现网 29 行全部同组同桶 | `docs_core/library_registry.py:80-92,408-427`；查询证据见本票讨论记录 |
| F2 | 导出唯一硬粒度闸 = 同组校验；包内 sqlite 是**整组文件**、快照是**整组 collection** | `corpus_package.py:179-183,193-213,426-433` |
| F3 | 组 sqlite 的 doc 键全表清单（12 张，含 FTS/vectors/corrections）= 拆并迁移与拆组脚本共同契约；**单一真相源 = `KbMigrator._DOC_TABLES`，切片模块直接 import** | `kb_migrator.py:309-315`；`scripts/split_sqlite_groups.py:26-39` |
| F4 | FTS 是普通 fts5 虚表（非 external-content），**可直接 INSERT SELECT 抽行**；按 doc 抽 FTS 已有先例 | `step05_sqlite_fts/store/canonical_sql_store.py:343-365`；`step10_export/export_artifacts.py:108-119` |
| F5 | 图谱 = 全局单文件 `data/knowledge/graph.sqlite`，行级 `library_id` 隔离；entities `UNIQUE(name,library_id)`、relations `UNIQUE(source_id,target_id,relation_type,library_id,doc_id)` | `paths.py:89-91`；`step07_graph/graph_store.py:29-49,290-303,315-382` |
| F6 | qdrant point payload 带 `library_id` 且已建 KEYWORD payload 索引；scroll 带向量、按过滤批量取点、set_payload 均已实现 | `step06_vectors/qdrant_vector_store.py:142-147,180-190,399-421,365-388` |
| F7 | 检索链路按库解析 sqlite/collection，多库请求按 collection 分组扇出（组内集合一次调用）——**每库独立桶天然可被检索** | `docs_service.py:296-301,311-330,375-382,1073-1088,1158-1186`；`step09_query/retrieve_service.py:275-277,289-318` |
| F8 | 本地降级路（`ANGINEER_DISABLE_LOCAL_FALLBACK` 关掉 HTTP 时的进程内路径）稠密/表格/公式按集合首库路由，**无跨组扇出**（已知缺口，本票只记录不修） | `step09_query/agent_port.py:116` |
| F9 | export 任务/单飞/一次性 ticket/流式 zip/前端五态弹框均已落地，v2 沿用同模式 | `services/docs-api/export_routes.py:31-59,124-193`；`corpus_package.py:528-619`；`apps/admin-web/src/components/kb-export/ExportPackageModal.vue` |
| F10 | import 唯一通道 = CLI，写 registry 行 + meta `nodes/tree_node`，**漏写 meta `libraries` 行**（`_switch` 注释明确「缺这行新库对读方不可见」）；meta libraries 是库清单主源 | `scripts/kb_corpus_import.py:131-161`；`kb_migrator.py:763-771`；`blocks_sql_store.py:415-434`；`docs_service.py:556-565` |
| F11 | 拆并迁移「同组同桶恒成立」是硬假设（collection/组文件任务期钉定 + 同组校验）；同组异构桶会静默错数据 | `kb_migrator.py:216-217,366-371,520-524` |
| F12 | 改组（编辑库）只改注册行并**重新指向新组默认桶**（不搬数据）：对独立桶导入库是一次数据失联雷 | `library_registry.py:242-270`；`docs_service.py:625-637` |
| F13 | 删库置 registry retired、清 meta/图谱/产物，但**不删本库 sqlite/collection/目录壳**（独立桶下成存储泄漏点） | `docs_service.py:681-704` |
| F14 | 容器内无 `kb_corpus_import.py`/`kb_corpus_export.py`：`.dockerignore` 与 `Dockerfile.backend` 是**文件名白名单**，两个脚本都未放行 | `docker/Dockerfile.backend:117-118`；`.dockerignore` scripts 段 |
| F15 | v1 契约测试锁 `build_package`/manifest 键（schema_version=1 等），v2 需重写 export 测试；import 侧 `SUPPORTED_SCHEMA={1}` 需扩 | `tests/unit/test_unit_kb_corpus_export.py`、`tests/unit/test_unit_kb_corpus_import.py`；`kb_corpus_import.py:38` |
| F16 | docs-api 挂路由模式与测试基建就绪（`main.py` include_router; `services/docs-api/tests/` 存在） | `services/docs-api/main.py:128` |
| F17 | **跨库实体引用真实存在**：add_principle/add_example/add_warning 按 `WHERE name=?`（不带 library_id）联结实体，可能挂到他库实体；`move_doc_graph` 显式容忍关系端点属于他库（`row["library_id"] != source_library_id: continue`）→ 图谱切片必须用**闭包口径**（先取本库 relation 端点与联结引用实体，再抽 entities），不能按 library_id 单过滤。单 doc 导出先例即闭包 | `graph_store.py:787,820,853,1071-1076`；`export_artifacts.py:269-285` |
| F18 | 图谱 FK 链：relations `REFERENCES graph_entities(entity_id)`、联结表 REFERENCES 父表/实体；GraphStore 连接 `PRAGMA foreign_keys=ON`。**实测 sqlite 3.45.3：`INSERT OR IGNORE` 对 immediate FK 违例=报错（等同 ABORT，整句失败），不静默跳行**——FK ON 下单事务里闭包缺料=报错回滚而非留悬空 | `graph_store.py:237,292-293,327-328,344-345,361-362`（实测脚本见本票讨论记录） |
| F19 | v2 不能指望 reembed：v1 `--reembed` 语义=跳过快照+提示跑 `rebuild_vectors.py`，而该脚本只覆盖默认单文件（不认独立桶）→ 定版 v2 导入阻断模型不一致 | `kb_corpus_import.py:13,227-231`；rebuild 覆盖范围见 docs-core 审计记录 |
| F20 | 边界外：`kb_migrator._relabel_meta` 的 file_path 改写按**绝对路径前缀**比较（`libraries_root_for` 绝对 vs `nodes.file_path` 已相对化）→ 恒不 match，走「告警+COALESCE 保旧路径」分支：迁移后重解析「源文件不存在」隐患（见文末另立票） | `kb_migrator.py:439-463`；`paths.py:94-107` |
| F21 | 前端链路是**两跳 nginx**：宿主机网关（`ai-proxy-locations.conf`，非 git）→ **frontend 容器 nginx（git 内、deploy 生效）** → docs-api。容器层 http 级 `client_max_body_size 200M`、`/api/` 300s——只改宿主机层，GB 级上传照样 413 | `docker/nginx/nginx.conf:21,96-105`（宿主机层见 AGENTS.md 拓扑） |
| F22 | 库文件根**按组不同**：knowledge 组=`knowledge/libraries`，evals 组=`evals/corpora/libraries`。导出代码 `iter_bundle_zip` 与 `_file_path_warnings` 仍写死 `knowledge/libraries`——导 `lab-firm-full` 会漏整个 `files/`，且 9,009 条 file_path 全误报 | `library_registry.py:47-66,430-440`；`corpus_package.py:198,423` |
| F23 | 删库是**同步逐篇**：9,276 节点/4.1G 分钟级；前端 `deleteLibrary` 仍默认 30s（`6f66b67d` 只修了节点/记录删除，漏整库）；`doc_catalog` 未清；`evals_corpus` 共享 16 行（11 active）→ 不能删容器 | `docs_service.py:681-704`；`knowledge.ts:227`；`apiClient.ts:10`；registry 查询 |

## 包格式定版（v2，两侧契约）

```
<组名>-<YYYYMMDD>.zip                      # 外层 bundle（ZIP_STORED，流式嵌套，不落盘）
├─ manifest.json                           # kind="bundle"；schema_version=2；embed_model；page_base=0；
│                                          # libraries[]：library_id/name/group_name/entry/sha256/bytes/counts；files{entry:sha256}
└─ libraries/<library_id>.zip              # 每个知识库一个自包含小包（可单独交付/单独导入）
     ├─ manifest.json                      # kind="library"；schema_version=2；library_id/name/group_name(原)；
     │                                      # embed_model；page_base=0；created_at；
     │                                      # counts{docs,chunks,vectors,graph_relations,graph_tables{逐表}}；warnings[]
     │                                      # files{包内相对路径: sha256}
     ├─ registry/rows.json                 # 本库 library_registry 行（含原 sqlite_file/collection，供追溯）+ 其组行
     ├─ meta/rows.json                     # 本库 nodes/tree_node + **meta libraries 行**（修复 F10 缺口）
     ├─ index/index.sqlite                 # 按库切片：12 张 doc 表（F3 清单；P2-0b 后含 doc_catalog = 13 张），DDL 原样
     ├─ files/<库根>/…                     # 文档树：knowledge 组=knowledge/libraries/<lib>/…；evals 组=evals/corpora/libraries/<lib>/…
     │                                      # 排除 documents/<doc>/parsed/{mineru_raw,popo}；不含 lib 根 index.sqlite
     ├─ qdrant/vectors.snapshot            # 本库向量快照（导出侧临时每库 collection 的原生快照）
     └─ graph/graph.sqlite                 # 本库图谱**闭包**切片（F17：relations/artifacts/deletions 按库；
                                            # entities = 本库 ∪ 关系端点 ∪ 联结引用，可含他库归属行）
```

导入侧映射（两侧同码，写死）：

| 包内条目 | 导入落位/动作 |
|---|---|
| `files/…` | 按相对 data 根路径原样放回（file_path 已在库根相对树下：knowledge 组=`knowledge/libraries/<lib>/documents/…`，evals 组=`evals/corpora/libraries/<lib>/documents/…`，零改写） |
| `index/index.sqlite` | `knowledge/libraries/<lib_id>/index.sqlite` |
| `graph/graph.sqlite` | **单事务**合并进全局 `knowledge/graph.sqlite`：固定顺序 **entities → artifacts(principles/examples/warnings/frameworks) → junctions → deletions → relations**；连接级 `PRAGMA foreign_keys=OFF`（必须在 `BEGIN` 前设置），事务内插入完成后跑 `foreign_key_check`，按主键签名只放行「目标原有 ∪ 包内自带」的悬空行，出现新增违例即 `ROLLBACK`；验证=逐表对账为主 + 新增悬空=0 |
| `registry/rows.json` | 改写后写 registry：`group_name=目标组`、`sqlite_file=knowledge/libraries/<lib>/index.sqlite`、`collection=<lib_id>`、`status=active` |
| `meta/rows.json` | `nodes`/`tree_node`/`libraries` 行 INSERT（冲突闸已挡重名） |
| `qdrant/vectors.snapshot` | recover 成本库 collection（改名能力见 P2-0；不行走临时恢复+复制兜底） |
| 两处 `manifest.json` | 全量 sha256 校验（外层校验小 zip，内层校验内容文件） |

闭包实体附加说明（F17）：小包里可能含**归属他库**的 entity 行（本库关系/联结引用所致）。若目标已有同 `(name, library_id)` 但不同 `entity_id` 的行，**P2-2 首版预检阻断**（提示先清目标同名实体，或另立「自然键重映射」票）；不得用 `INSERT OR IGNORE` 静默丢实体——关系/联结会留下悬空。目标无同名实体时原样插入。

---

## Stage P1：导出 v2（切片 + 嵌套 zip 流式）

### Task P1-1: 嵌套 zip 流式小验证（spike，半天）

**Files:** `tests/unit/test_unit_corpus_nested_zip.py`（新建，验证后并入 P1-5 测试）

- [x] **Step 1:** 写一个最小实验：外层 `zipfile.ZipFile` 写入非 seekable sink，对内层 zip 也用 `ZipFile` 写进外层 entry 的写句柄（包一层计字节/算 sha256 的 wrapper），断言：内层 zip 解出后是合法 zip 且文件完整、外层 manifest 可读。
- [x] **Step 2:** 若 zipfile 对「entry 写句柄内再开 zipfile」环境有坑（seek/tell 断言等），记录坑与替代法：**小 zip 先落临时文件再流入外层**（每库峰值多一份库切片临时磁盘，代码更简单）。
- [x] **Step 3:** 结论写进实现注释（`tests/unit/test_unit_corpus_nested_zip.py` docstring：py3.11.17/3.12.6 双端实测通过；契约=ZipByteCounter 无 tell 强制 data descriptor 路径；force_zip64 路径已验；兜底=临时文件）；已并入检查点 `f48cc5ec`。

### Task P1-2: sqlite 按库切片模块（TDD）

**Files:**
- Create: `services/docs-core/src/docs_core/corpus_slicing.py`
- Test: `tests/unit/test_unit_corpus_slicing.py`（新建）

- [x] **Step 1: 失败测试**——造 2 库的组 sqlite 夹具（复用 `test_unit_kb_corpus_export.py:14-55` 的建库姿势：真 sqlite + 12 表 + FTS 行，两库各插文档），断言：
  - `build_library_sqlite_slice(data_root, library_row, out_path)` 出的库只含目标库行（12 表逐表 COUNT，另一库 0 行）；
  - FTS 可查（对切片跑一条 `SELECT ... MATCH`）；
  - DDL 原样（表/索引/触发器来自源 `sqlite_master`，FTS 用 `CREATE VIRTUAL TABLE ... USING fts5(...)` 重建后 INSERT SELECT——抄 `export_artifacts.py:108-119`）；
  - 源库缺表时跳过不炸（旧库兼容）。
- [x] **Step 2: 跑→FAIL** → **Step 3: 实现**：
  - 读侧先 `checkpoint_sqlite`（复用 `corpus_package.checkpoint_sqlite`），ATTACH 源库，单连接读事务取一致快照；
  - 表清单**直接 import 复用 `KbMigrator._DOC_TABLES`**（F3 单一真相源，勿再声明同步）；施工时对照 `sqlite_master` 复核一次有无漏网 doc 键表（有则先补进 `_DOC_TABLES`）；
  - 目标库先按源 `sqlite_master` 重建 DDL（`SELECT sql FROM sqlite_master WHERE tbl_name IN (...)`，表+索引+触发器），再 `INSERT INTO ... SELECT ... WHERE doc_id IN (SELECT doc_id FROM canonical_documents WHERE library_id=?)`；
  - 返回 `{docs, chunks, bytes}` 计数供 manifest。
  - 施工注：FTS 可检索列实测=section_path/text_ngrams（text_clean UNINDEXED），测试按真实 schema 造 ngram；.git 交付差异=返回键含 tables 逐表计数。
- [x] **Step 4: 跑→PASS** → [x] **Step 5: commit** `feat(docs-core): 语料包 v2 组 sqlite 按库切片`（并入检查点 `f48cc5ec`）

### Task P1-3: 图谱按库闭包切片（TDD）

**Files:**
- Modify: `services/docs-core/src/docs_core/corpus_slicing.py`
- Test: `tests/unit/test_unit_corpus_slicing.py`（追加）

- [x] **Step 1: 失败测试**——造含 2 库图谱的 graph.sqlite 夹具（按 `graph_store.py` 建表，含**跨库引用场景**：A 库关系端点是 B 库实体、A 库 principle 的联结挂 B 库实体），断言 `build_library_graph_slice(graph_db, library_id, out_path)` 用**闭包口径**（F17）：
  - relations/artifacts/deletions 按 library_id=A 过滤（「B 库 0 行」断言**只加在这些表**上，不加 entities）；
  - entities = 闭包集合：`library_id=A ∪ 本库关系端点 ∪ 本库联结引用实体`（允许含他库归属行；断言无闭包外杂行）；
  - junctions（`*_entities`）按本库父 id 抽全行；
  - 对切片跑 `PRAGMA foreign_key_check` → 空（闭包完整性的硬断言）；
  - 空图谱（库无行）出合法空库不炸。
- [x] **Step 2: 跑→FAIL** → **Step 3: 实现**（参照 `export_artifacts.py:243-289` 的单 doc 闭包实现，范围放大到单库；切片内写入顺序 entities → artifacts → junctions → relations，与导入合并同序；**切片构建连接 FK OFF 纯拷贝**——让漏闭包以 `foreign_key_check` 报告形式暴露完整诊断，而非中途 abort）→ **Step 4: 跑→PASS**
  - 施工注：闭包用纯 SQL（entities WHERE library_id=? OR 端点/联结引用 IN 子查询，免 Python 侧 id 清单）；写入序 entities → artifacts → junctions → deletions → relations；夹具侧 GraphStore 构造泄漏连接（引用循环）需 gc.collect() 才能删临时目录（Windows 锁）。
- [x] **Step 5: commit** `feat(docs-core): 语料包 v2 图谱按库闭包切片`（并入检查点 `f48cc5ec`）

### Task P1-4: 向量按库快照（临时 collection，TDD）

**Files:**
- Modify: `services/docs-core/src/docs_core/corpus_slicing.py`
- Test: `tests/unit/test_unit_corpus_slicing.py`（追加，qdrant 侧 monkeypatch）

- [x] **Step 1: 失败测试**——monkeypatch qdrant 交互，断言流程：建临时集合（`exp-tmp-<lib>-<ts>`，配置克隆源集合：dim/metric/量化/HNSW，payload 索引 doc_id/library_id）→ 按 `library_id` 过滤 scroll（`with_vectors=True`，批次 1024）→ upsert 拷贝（保 point id + payload 原样，批次 256）→ 建快照返回 `(name,size)`；finally 删快照+临时集合；`copy_collection_points(src,dst,flt)` 提成公共函数（导入兜底路径复用）。
  - 施工注：落地为 `library_vector_snapshot()` 上下文管理器（yield `{collection,snapshot,size,points,temporary}`，退出删快照+临时集合；调用方在 with 内把快照流进包）；`copy_collection_points(client,source,target,flt)` 公共函数；快照建失败路径也清临时集合；`cleanup_stale_temp_collections()` 供 P1-5 导出开局调用；`TEMP_COLLECTION_PREFIX` 常量。
- [x] **Step 2: 跑→FAIL** → [x] **Step 3: 实现**（`QdrantVectorStore._get_client` 已有；REST 快照复用 `corpus_package.create_snapshot/open_snapshot/delete_snapshot`；导出开始清扫残留 `exp-tmp-*`）
  - 施工注：客户端工厂直接走 `QdrantClient`（与 QdrantVectorStore 同配置：url/key/timeout/trust_env=False），不复用 store 实例。
- [x] **Step 4: 优化项**：目标 collection 若**仅本库独占**（扫全 registry 无第二个库指同一 collection）→ 跳过拷贝直接快照源集合。
  - 施工注：`library_owns_collection_exclusively(library_id, collection)`，**含 retired 一起扫**（退役库残留向量在源集合里）；空 collection 名返回 False。
- [x] **Step 5: 跑→PASS** → [x] **Step 6: commit** `feat(docs-core): 语料包 v2 向量按库快照（临时 collection + 独占直取）`（并入检查点 `f48cc5ec`）

### Task P1-5: `corpus_package.py` 重写为 v2（扫描 + 嵌套流式）

**Files:**
- Modify: `services/docs-core/src/docs_core/corpus_package.py`（v1 导出代码删除；保留 `checkpoint_sqlite`/`ExportTasks`/快照 REST 工具）
- Modify: `tests/unit/test_unit_kb_corpus_export.py`（重写为 v2 契约）

- [x] **Step 1: 失败测试（新契约）**：
  - `scan_selection` 返回逐库明细（files_bytes/sqlite 估算/vector_points/snapshot 估算/counts）+ 总量的结构；**无同组校验、无 peers 警告**；
  - `iter_bundle_zip(libs)` 产出的 zip：外层含 `manifest.json` + `libraries/<lib>.zip`；内层含定版全部条目（index/files/qdrant/graph/registry/meta/manifest）；两层 manifest 键齐全、sha256 可对账；内层可单独解出并再次当输入（reader 自洽）。
  - `with_vectors=False` 时无 qdrant 条目（快照环节跳过）。
- [x] **Step 2: 跑→FAIL** → [x] **Step 3: 实现**：
  - `scan_selection`：库存在性校验（去同组闸）；**逐库 `assert_library_not_migrating(lib_id)`**（迁移中库拒绝出包，防切片不一致；`kb_migrator.py:66`，用法同 `docs_service.py:720`）；sqlite 估算 = 组库体积 × 本库 chunk 占比（`canonical_documents`/`canonical_chunks` COUNT，**仅参考值**，不设验收门槛），vector_points = qdrant `count` 按 `library_id` 过滤；
  - `iter_bundle_zip`：逐库构建切片临时文件（P1-2/3）→ 拉快照（P1-4）→ 内层 zip 流式（manifest 最后写、sha256 边流边算）→ 流入外层 → 临时文件用完即删；进度回调与取消检查沿旧模式（`on_stage` 增加 `slice` 阶段）；
  - **切片前逐库重闸** `assert_library_not_migrating`（scan 闸后到构建间有迁移启动时序窗；重闸廉价，把窗口收到单库切片时长；残余窗口见风险表）；
  - `embed_model` 在导出开始时**固化一次**（settings console 热替换窗口内若中途取值，manifest 标签可能与快照向量不同代；一行改动关窗）；
  - 文档树遍历复用 `_iter_doc_files`，**新增排除 lib 根 `index.sqlite`**（防再导导入库时把旧切片带进包）；
  - 抽 meta 行时**校验 file_path**（Stage A 相对化契约）：非 `knowledge/libraries/<lib>/documents/…` POSIX 相对（绝对路径/含反斜杠/他库前缀）→ 逐条 warning + 计数写 `manifest.warnings`（不阻断；防把数据迁移契约的雷打进自包含包）。
  - 施工注：快照在 stream 前逐库预建并随 ExitStack 存活到包尾（进度分母含真实快照 size）；图谱缺全局库时出空切片；`read_meta_rows` 返回增 `libraries` 键（F10 补齐，表缺失自动跳过）；内层 files 弧名带 `files/` 前缀按定版。
- [x] **Step 4: 跑→PASS** → [x] **Step 5: commit** `feat(docs-core): 语料包 v2 导出核心（每库自包含小 zip + 大包嵌套流式）`（并入检查点 `f48cc5ec`）

### Task P1-6: 路由/CLI/前端接线

**Files:**
- Modify: `services/docs-api/export_routes.py`（preview 返回逐库明细；stream 走 `iter_bundle_zip`；文件名 `<组名>-<日期>.zip`；同组校验调用点删除）
- Modify: `scripts/kb_corpus_export.py`（`--libs` 产出 bundle zip 到 `--out`；保留 `--no-vectors`；`--tar/--exclude-doc-dirs` 语义保留）
- Modify: `apps/admin-web/src/components/kb-export/ExportPackageModal.vue`、`apps/admin-web/src/api/knowledge.ts`
- Test: `services/docs-api/tests/`（preview 响应形状，轻量）

- [x] **Step 1:** 后端两处接线 + preview 响应增字段（保留旧字段名兼容前端渐进改）→ 跑测试
  - 施工注：ticket 端点廉价校验从 `validate_selection` 换 `read_registry`（v2 无同组闸）；preview 逐库明细 {files_bytes,sqlite_estimate,vector_points,snapshot_estimate,counts,total_estimate}，顶层保旧字段名（sqlite_bytes=逐库估算和）+ `embed_model`/`kind`/`schema_version`；stream 文件名 `<组名>-<北京时间日期>.zip`。
- [x] **Step 2:** 前端：删除「未全选警告/建议全选」（`ExportPackageModal.vue:183-191,227-232` 一带文案），预览区显示**逐库体积**（大包总大小 + 各小包列表）；其余五态机/进度/取消不动
- [x] **Step 3:** 验证：`pytest tests/unit -k corpus`；`pnpm --filter admin-web exec vue-tsc -b`
  - 实测：corpus 27 passed；docs-api tests 32 passed（含新 `test_export_preview_shape.py`）；vue-tsc 干净；CLI `--help` 可跑。
- [x] **Step 4: commit** `feat(export): 管理后台/CLI 切换每库自包含语料包 v2`（并入检查点 `f48cc5ec`）

### Task P1-7: P1 验收（本地小库）

- [x] 导 `default`（小库）单库 + 导 `standards` 组三库（可选跳过向量先验结构）：解开大包验小包独立、manifest/sha256 对账；**不设估算误差门槛**（FTS 体积与 chunk 数不成比例，F4；preview 估算仅参考，最终以包内 manifest 实测 `bytes` 为准）
- [x] 中途取消 → 无 qdrant 临时集合/快照残留（`GET /collections` 与快照列表核对）

**执行记录（2026-10-18，本地 dev：qdrant localhost:6333 + data/ 生产数据）**
- `default` 带向量：`system-20261018.zip` 35MB；内层 109 条目两层 sha256 全对账；FTS MATCH 命中；counts={docs:9,chunks:701,vectors:973,graph_relations:339,graph_fk_violations:436}。
- standards 三库 `--no-vectors`：`standards-20261018.zip` 9748MB（**实测内层小包 >4GiB → 触发 zip64 路径**）；std-water 内层 23728 条目 sha256 全对账；FTS 命中。
- 取消/断连演练：显式 `is_cancelled` 翻转与 `gen.close()` 两路中断后 `GET /collections` 均无 `exp-tmp-*` 残留。
- 验收抓到并修复 3 处实采坑：
  1. `_create_collection_like` 把 GET 回的 `HnswConfig` 直传 create（要 `HnswConfigDiff`）→ pydantic ValidationError；已按字段过滤转换 + 克隆 `sparse_vectors`；单测假身升级为真模型校验（`test_unit_corpus_slicing.py`）。
  2. 内层小包超 4GiB 时外层 entry 需 `force_zip64=True`（close 报 "File size too large"）；已加。
  3. 中断时未收尾的 ZipFile 在 GC 期 `__del__` 对已断 sink 写尾部报「I/O on closed file」噪声；已加静默收尾守卫。
- 实采发现（导入侧设计输入，P2 对齐）：
  - **源 graph.sqlite 自带 436 条历史悬空行**（实体删除残留：relations 66+46、warning/principle/example 联结 324，集中在 default 库）。切片定版=**忠实镜像 + 计数上报**：`counts.graph_fk_violations`（机器读）+ manifest.warnings 人读行；切片**不得引入新悬空**（验收脚本按「源有父、切片无」判缺漏）。P2 导入的 FK 检查须据此区分「切片缺漏 vs 源数据脏」，勿硬阻断。
  - `registry.sqlite` 的 `library_groups` 现为**空表**（组名只在 library_registry 行上）→ registry/rows.json 的组行按源实况为空，包结构不受影响。
  - meta `libraries` 行主键列名是 `id`（非 library_id，F10 落包已含）。
  - `default` 库 3 条 nodes.file_path 为旧绝对路径（`knowledge_base/libraries/...` 与 `\app\data\...`）→ 被 file_path 警告网住（P1-5 设计生效），对应 F 数据迁移雷。

### Task P1-8: evals 组库根路径修正（导出文档树 + file_path 告警）

**背景（2026-10-20 实测）：** knowledge 组的库根是 `knowledge/libraries/<lib>`，evals 组是 `evals/corpora/libraries/<lib>`（F22）。`iter_bundle_zip` 的 `lib_root` 与 `_file_path_warnings` 仍写死 `knowledge/libraries` → 导 `lab-firm-full` 时 `files/` 为空、9,009 条 file_path 全误报。**先做本项，再做 P2-0b/P2-2。**

**Files:**
- Modify: `services/docs-core/src/docs_core/corpus_package.py`（`iter_bundle_zip` 的 `lib_root`；`_file_path_warnings`）
- Test: `tests/unit/test_unit_kb_corpus_export.py`

- [ ] `lib_root` 改用 `library_registry.resolve_libraries_dir(lib_id)`（evals 组返回 `evals/corpora/libraries`），不再写死 `data/knowledge/libraries/<lib>`。
- [ ] `_file_path_warnings` 的合法前缀按该库根相对 data 根计算：`knowledge/libraries/<lib>/documents/` 或 `evals/corpora/libraries/<lib>/documents/`；绝对路径/反斜杠/他库前缀照旧告警。
- [ ] `files/` 弧名仍按 data 根相对路径（`files/<库根>/...`），导入侧不改。
- [ ] 测试：knowledge 组与 evals 组各一库，断言 `files/` 非空、路径正确、file_path 无告警；`pytest tests/unit -k corpus` 绿。
- [ ] commit `fix(docs-core): 语料包导出按组解析库根（evals/corpora 文档树不漏）`

---

## Stage P2：导入核心（CLI，v2 only）

### Task P2-0: qdrant recover 改名能力实测（卡点，先于实现）

- [x] 在开发机起临时 qdrant（或拿一个可弃 collection）：先试**集合级路径** `POST /collections/<target>/snapshots/upload`（恢复进任意名 collection，预判大概率可行；body 带 `location`/`priority`）→ 不行再试全局快照 `POST /snapshots/upload` + `POST /snapshots/<name>/recover` 改名姿势（body `{"collection_name": ...}`）。
- [x] 结论二选一写进代码注释：**能改名** → 导入直接 recover 成 `<lib_id>`；**不能** → 走兜底：recover 成临时名 → `copy_collection_points`（P1-4 公共函数反向用）拷进 `<lib_id>` → 删临时集合。
- [x] 实测记录（命令+结果）贴进本票执行记录。

**执行记录（2026-10-18，本地 qdrant 1.19.0，httpx multipart）**
- **结论：能改名（姿势1 即可，无需全局快照兜底）**。`POST /collections/p2-0-beta/snapshots/upload?priority=snapshot`（multipart `snapshot=@file`）把 p2-0-alpha 的快照恢复进 **不同名** p2-0-beta：200 + `points_count=3`；payload 保真；**payload 索引随快照恢复**（p2-0-gamma 建了 `library_id` keyword 索引 → 跨名恢复进 p2-0-delta 后 `payload_schema=['library_id']`）。
- 导入实现定版：内层 `qdrant/vectors.snapshot` **直接 multipart 上传到 `/collections/<lib_id>/snapshots/upload`**（目标名即库名，原快照名无关）；P2-2 代码注释引用本记录；兜底拷贝路径（copy_collection_points）**不启用**（函数保留：导出侧 P1-4 仍在用）。
- 附加实测（冲突闸输入）：**目标集合已存在时上传不报错**（200，内容被快照覆盖）→ 冲突闸不能指望 qdrant 拒绝，`<lib_id>` collection 名占用前置检查（P2-1）是唯一防线。
- 探针集合（p2-0-*）已全部删除，本地 qdrant 无残留。

### Task P2-0b: HarveyLab 合流：`doc_catalog` 纳入切片（P2-2 前后均可，建议先做）

**前置：** P1-8 先做（否则 evals 组 `files/` 仍漏）；`doc_catalog` 已在 v0.3.0 保留并扩列（`title_semantic` / `doc_type_semantic` / `title_source`），DDL 与写入链路已提交；切片按 `SELECT *` 自动跟随新增列。

**Files:**
- Modify: `services/docs-core/src/docs_core/kb_migrator.py`（`_DOC_TABLES`）
- Modify: `scripts/split_sqlite_groups.py`（同名清单逐字同步）
- Test: `tests/unit/test_unit_corpus_slicing.py`、迁移/拆组相关测试

- [ ] 把 `doc_catalog` 加入 `KbMigrator._DOC_TABLES` 与 split 脚本清单；切片自动跟随（表有 `library_id` 列，按库过滤；无表跳过，旧库兼容）。
- [ ] 测试：有表/无表两态；两库夹具断言本库行保留、他库 0 行；split/migrate 后行数不变。
- [ ] 同步包格式/F3 的「12 张」→「13 张」；表名/DDL 以 `doc_search.ensure_catalog` 当前定义为准。
- [ ] commit `fix(docs-core): doc_catalog 纳入 doc 键表切片与拆并`

**背景（2026-10-20 实测）：** 核心目标是 `lab-firm-full`：**9,009 行 / 267 matter**（10-18 报告为 9,008 / 266）。当时全表 21,802 行还含 `lab-firm-dms` 9,276 行（未使用、业主已准备删）、`omnidocbench` 2,609 行等；P2-0b 的理由是 `lab-firm-full` 这 9,009 行，其他库随切片按 `library_id` 自然带上。`_DOC_TABLES` 12 表不含它；不补则导入后 `doc_search` 退化为按文档分组，按 matter 枚举质量下降（不报错）。

**HarveyLab 结论（2026-10-20 复核）：** 100 题报告 §4 明确保留 `doc_catalog`/`doc_search`/`doc_read`；被否的是 P1/P3/P0.5/P2.1/P2.2 链路实验与 Harness2 上游试跑，不影响本表。Harness2 的「按 matter 遍历」反而依赖它。

### Task P2-1: bundle reader + 闸（TDD）

**Files:**
- Modify: `services/docs-core/src/docs_core/corpus_package.py`（导入侧函数：`open_bundle`/`parse_bundle`、闸函数）
- Test: `tests/unit/test_unit_kb_corpus_import.py`（扩 v2；v1 用例随 P2-3 删除）

- [x] 实现 `open_bundle(path)`：识别三种输入——v2 大 zip（manifest.kind=bundle）、v2 小 zip（kind=library）、v1 目录/tar（走旧路径）。返回 `{libraries:[{library_id, inner_bytes, manifest, files_index}], embed_model, ...}`
- [x] 闸扩展（纯函数，沿用现有可测风格）：
  - `check_schema_gate`：`SUPPORTED_SCHEMA={1,2}`；
  - `check_embed_gate`：逐库（v2）对账 `EMBEDDING_CONFIGS` 首项——**不一致即阻断**（定版 b，F19；报错文案给「以目标模型重出包」指引，**v2 不留 `--reembed` 口**）；v1 旧语义不动；
  - `check_conflict_gate` 增：目标 registry/meta 无同 `library_id`、nodes 无同 id、**`<lib_id>` collection 名未被占用**（registry 行集合 + qdrant collections 列表）、目标 `knowledge/libraries/<lib>/index.sqlite` 不存在；另查**闭包实体行**：小包内归属他库的 entity 与目标同 `(name,library_id)` 不同 `entity_id` → 告警（不阻断，对账+FK 检查兜底）；
  - `check_package_files`：两层 sha256（外层校验小 zip 字节；内层校验条目文件）。
- [x] 测试：篡改内/外层 sha256、缺文件、schema=999、library 已存在、collection 名冲突 → 均中止且报原因。
- [x] commit `feat(docs-core): 语料包 v2 读取与预检闸（含 v1 兼容识别）`（并入检查点 `f48cc5ec`）

**执行记录（2026-10-18）**
- `corpus_package.py` 导入侧落地：`BundleError(ValueError)`、`BundleLibrary`/`Bundle`（dataclass）、`open_bundle`（contextmanager：v2 大包内层小包**流式落临时文件**（`_spool_zip_entry` 边落边算外层 sha256/bytes，9GB+ 不整读内存）、v2 小包直用句柄、v1 目录/tar 识别后 raise/转交；kind/schema/内外层 embed_model 一致性校验；ExitStack 统一收尾句柄+临时文件）、`check_package_files`（外层 sha256+bytes / 内层逐条目 sha256 + 缺文件 + 多出未登记条目）、`check_schema_gate({1,2})`、`check_embed_gate`（无 embed_model 也阻断；文案含「以目标模型重出包」且不含 reembed 字样）、`check_conflict_gate`（纯输入四类 clash + 闭包实体重名 warning）。
- 测试扩至 **22 passed**（原 v1 8 用例保留不动 + 新增 14：V2OpenBundleTests 4 / V2IntegrityTests 5 / V2GateTests 5；fixture=`_inner_zip_bytes`/`_bundle_zip` 手工构造小 v2 包，篡改=manifest 记原 sha 而字节改）。
- 回归 `python -m pytest tests/unit -k "corpus" -q` → **42 passed**（28 旧 + 14 新）。

**2026-10-18 范围修订：** v1 兼容移出范围（旧包暂无人用）。恢复施工时 `open_bundle` 只认 v2、`SUPPORTED_SCHEMA={2}`、删除 v1 分支与 8 个旧用例；当前检查点代码仍保留 v1 分支，不影响 v2，清理并入 P2-3。

### Task P2-2: `apply_import` 应用逻辑（TDD）

**Files:**
- Modify: `services/docs-core/src/docs_core/corpus_package.py`
- Test: `tests/unit/test_unit_kb_corpus_import.py`（追加，qdrant 快照环节 monkeypatch）

- [ ] **预检补强（P3 上传前必须）**：`library_id` 安全正则（现网存在 `lib-DredgeAI-a5e1` 这类大写，允许 `[A-Za-z0-9_-]`，拒绝空/路径分隔/`..`）+ `files/` 条目必须以 `knowledge/libraries/<lib_id>/` 开头、拒绝绝对路径/`..`/反斜杠；导入落位路径由校验后的 id 生成，不直接用包内值。
- [ ] 逐库执行（顺序固定，任一步失败即停并报「已完成的步骤」，重跑靠冲突闸兜底不幂等）：
  1. 解内层 zip 到 `data/scratch/imports/<task>/<lib>/`（校验后）；
  2. `files/…` 放回 data 根；
  3. `index/index.sqlite` → `knowledge/libraries/<lib>/index.sqlite`；
  4. graph 切片合并进全局 `graph.sqlite`（目标不存在先建 schema）：连接级 `PRAGMA foreign_keys=OFF`（必须在 `BEGIN` 前设置），**单连接单事务**；固定顺序 **entities → principles/examples/warnings/frameworks → junctions → deletions → relations**；插入完成后在事务内对目标跑 `PRAGMA foreign_key_check`，按主键签名（`graph_relations.relation_id`；三张联结表复合键）与「目标原有悬空 ∪ 包内自带悬空」对账——只允许这两类，出现新增违例即 `ROLLBACK` 并报明细；包内自带悬空签名从 `graph/graph.sqlite` 预先算出（`counts.graph_fk_violations` 只作计数提示，不用于判据）；
  5. meta 行 INSERT：`nodes`/`tree_node`/`libraries`；
  6. registry 行（改写表见「包格式定版」映射表；组不存在时按 slug 建自定义组，display_name 取原组 display 或用户输入；**内置组跳过建组**，源包 `groups` 行不得写入目标）；
  7. 快照恢复（P2-0 确定的路径；v2 无 reembed 分支——模型不一致在闸就断了；无 `qdrant/vectors.snapshot` 的 `--no-vectors` 包跳过此步与向量对账）；
  8. 对账**逐表**：`canonical_documents`==counts.docs、qdrant count(collection)==counts.vectors、图谱按 `counts.graph_tables` 逐表对（entities/relations/artifacts/junctions/deletions 都查——只数 relations 会漏丢实体）；图谱落地后新增 `foreign_key_check` 违例=0（允许并记录包内继承悬空）。
- [ ] 测试：tmp data 根全流程（快照环节 fake；含一个跨库实体的闭包切片）→ 断言 registry/meta/graph/index 落位、逐表计数对账、合并后新增 `foreign_key_check` 违例=0；另造一个含 436 类悬空基线的小包，断言合并成功且新增=0、超出基线的违例回滚；再跑一次 → 冲突闸拒。
- [ ] commit `feat(docs-core): 语料包 v2 导入应用（独立桶落位 + 图谱合并 + 对账）`

### Task P2-3: CLI v2 单格式 + 容器白名单（并清 v1 死代码）

**Files:**
- Modify: `scripts/kb_corpus_import.py`（v2 单格式；`--group`/`--group-display-name` 新增；`--only lib1,lib2`；**删除 v1 目录/tar 旧路径与 `--reembed`**；收到 v1 包硬报错「v1 旧包不再支持，请用 v2 重新导出」）
- Modify: `services/docs-core/src/docs_core/corpus_package.py`（删除 `open_bundle` 的 v1 分支；`SUPPORTED_SCHEMA={2}`）
- Modify: `tests/unit/test_unit_kb_corpus_import.py`（删除 8 个 v1 用例）
- Modify: `docker/Dockerfile.backend:118`、`.dockerignore`（放行 `kb_corpus_import.py`、`kb_corpus_export.py`——F14，缺一构建即失败）
- Test: 脚本 dry-run 输出（手工验收）

- [ ] Step 0: 清 v1：删 `open_bundle` 的 v1 目录/tar 分支、脚本旧落盘函数、`--reembed` 与 8 个旧用例；`SUPPORTED_SCHEMA` 收为 `{2}`；v1 包给明确升级提示
- [ ] Step 1: CLI：`--dry-run`（默认）解析包 → 打印逐库落位预览（目标组/collection/路径/体积/counts）+ 闸结果；`--apply` 执行；末尾打印验收清单（重启或探针）
- [ ] Step 2: 白名单两处同改，`docker build`（或至少 `docker build --target` 校验层）确认 COPY 不再 file not found
- [ ] Step 3: commit `feat(scripts): 语料包 v2 导入 CLI（单库 zip/大包）+ 清 v1 旧路径 + 容器白名单放行`

### Task P2-4: reembed 口径定版 b（收口，不再二选一）

**已定版（2026-10-17 评审）：v2 导入不支持 reembed**——`rebuild_vectors.py` 只覆盖默认单文件（不认独立桶，F19），扩展属另立票范围；与其半吊子不如阻断。

- [ ] 落地三点，文案逐字一致（CLI 报错 / P3-1 预检响应 / P3-2 前端提示）：**「embed 模型不一致，v2 导入不支持 reembed；请用目标环境模型重新导出」**
- [ ] 若确有跨模型迁移需求 → 另立票「rebuild_vectors 支持 `--library`（独立桶自嵌）」，本票只记录
- [ ] commit `docs(import): v2 reembed 口径定版（阻断+指引）`

### Task P2-5: P2 验收（本地小库往返）

- [ ] 本地导出 `default` 单库小 zip → 改 `ANGINEER_DATA_ROOT` 指临时根（或直接备份后删）→ CLI `--dry-run`/`--apply` → 断言：registry/meta/graph/index 落位、FTS 检索命中、`/pdf` 探针 200（起临时 docs-api 或直接 store 层读）
- [ ] 同一小 zip 再导一次 → 冲突闸拒绝；大包 `--only` 只导一个 → 另一个不进注册表

---

## Stage P3：HTTP 导入 + admin-web 上传 UI

### Task P3-1: docs-api 导入路由（镜像 export 模式）

**Files:**
- Create: `services/docs-api/import_routes.py`；Modify: `services/docs-api/main.py`（挂 `/api/knowledge/imports`）
- Test: `services/docs-api/tests/`（上传落盘 + 闸拒绝的最小用例）

- [ ] 端点（全部 `Depends(resolve_admin_session)`）：
  - `POST /imports/upload`（multipart，流式落 `data/scratch/imports/<task_id>/package.zip`）→ 解析+闸 → 返回预览：逐库 {library_id,name,原组,counts,sizes}、建议组、冲突与告警（embed 不一致=阻断，文案按 P2-4 定版 b 逐字一致）
  - `POST /imports/{task_id}/apply` body `{group_name, group_display_name?, libraries[]}` → 后台线程执行（单飞闸；**应用阶段不可取消**，上传/预检阶段可弃）→ 阶段进度：`slice-copy/meta/registry/graph/vectors/verify/reload`
  - `GET /imports/{task_id}/status`；`DELETE /imports/{task_id}`（仅未 apply 时清暂存）
  - 成功后 `get_docs_service().reload_scope_cache()`；失败保留暂存目录供排障（列出路径）
- [ ] 测试：upload 大小/格式守卫、apply 前置校验（组名合法）、进程内任务表状态机
- [ ] commit `feat(docs-api): 语料包 v2 导入路由（上传/预检/应用/进度）`

### Task P3-2: admin-web 导入弹框

**Files:**
- Create: `apps/admin-web/src/components/kb-import/ImportPackageModal.vue`
- Modify: `apps/admin-web/src/components/MultiLibraryManager.vue`（头部加「导入语料包」按钮，克隆导出按钮形态）、`apps/admin-web/src/api/knowledge.ts`（uploadImport/applyImport/getImportStatus/deleteImport）
- 参考：`ExportPackageModal.vue`（五态机/轮询/进度模式）、`SplitMergeWizardModal.vue`（组下拉+新建组输入）

- [ ] 流程：选文件（`accept=".zip"`）→ 上传进度（xhr/fetch 可拿上传阶段）→ 预检结果（逐库卡片：名称/文档数/体积/图谱关系数）+ 目标组选择（已有组下拉 + 「新建组」name/display 输入）→ 库勾选（默认全选）→ 应用进度（阶段文字+库级进度）→ 完成（提示可直接使用；失败给原因+暂存路径）
- [ ] 文案：embed 不一致 → 直接阻断（文案按 P2-4 定版 b 逐字一致）；应用不可取消明示
- [ ] 验证：`pnpm --filter admin-web exec vue-tsc -b` + 本地手测（dev 起 docs-api）
- [ ] commit `feat(admin-web): 语料包导入上传 UI`

### Task P3-3: 网关两层运维项（容器层入 git 随 deploy；宿主机层手工报备）

链路**两跳都要张口**，缺一层即 413/超时（F21）：
```
浏览器 → 宿主机 nginx（ai-proxy-locations.conf，非 git）→ frontend 容器 nginx（docker/nginx/nginx.conf，git 内）→ docs-api
```

- [ ] **容器层（本票代码改动，随 deploy 生效）**：`docker/nginx/nginx.conf` 加专用 location（`^~ /api/knowledge/imports/`，形态抄 `/api/files` :84-94）：
  - `client_max_body_size 0`（http 级 :21 的 200M 是全局默认，GB 包必 413）；
  - `proxy_request_buffering off`（大包直传上游，不在容器落整份临时文件）；
  - `proxy_read_timeout/proxy_send_timeout 600s`；
  - 别动 `^~ /api/knowledge/internal/` 403 块（:141；更长前缀仍优先，顺序无虞）。
- [ ] **宿主机层（手工，不入 git）**：`/etc/nginx/ai-proxy-locations.conf` 同义放行（`client_max_body_size 0` + 长 timeout）；改完 `nginx -t && systemctl reload nginx`。**动手前向用户报备**。
- [ ] 验证：`docker compose up -d frontend` 后上传小文件走通 / 大文件（>200M）复测——两层任一未放行即 413 可复现对照。

### Task P3-4: P3 验收

- [ ] 开发环境 up 容器，走 UI 完整导一个真实小库 → 上传 → 应用 → 检索探针 + 概览页可见新库（组归属正确）
- [ ] 断点：上传中途关页面 → 暂存目录可清（DELETE 端点）；apply 中途杀进程 → 重启后冲突闸拦住重导的半成品（或手工清理指引输出）

---

## Stage P4：保护与收尾

### Task P4-0: 删库异步化 + 共享桶清理（后端 + admin-web）

**背景（2026-10-20 实踩）：** `delete_library` 同步逐篇清 9,276 节点（lab-firm-dms/4.1G），前端 `deleteLibrary` 仍是默认 30s（F23）；`6f66b67d` 只修了节点/记录删除，漏整库。另 `doc_catalog` 未清，`evals_corpus` 共享 16 行不能删容器。

**Files:**
- Create: `services/docs-core/src/docs_core/library_delete.py`（任务表 + worker + 批量清理）
- Modify: `services/docs-core/src/docs_core/library_registry.py`（`STATUS_DELETING`）
- Modify: `services/docs-api/docs_routes.py`（DELETE 202 / GET 状态 / 重试）
- Modify: `services/docs-core/src/docs_core/docs_service.py`（拆出批量清理；保留同步入口给测试/CLI）
- Modify: `apps/admin-web/src/api/knowledge.ts`、`apps/admin-web/src/components/MultiLibraryManager.vue`（进度弹框）
- Test: docs-core 删库测试、docs-api 路由测试、`vue-tsc -b`

- [ ] **任务与接口**：`DELETE /libraries/{id}` 立即 `202 {task_id}`；同库已有任务 → 409；`GET /libraries/deletions/{task_id}`、`GET /libraries/{id}/deletion` 返回 stage/progress/error；单飞 worker；启动时把遗留 `deleting` 标失败并可重试。
- [ ] **状态**：registry 增 `deleting`；开始置 deleting，成功置 retired；失败保留 deleting + 任务错误，不回 active。
- [ ] **批量清理顺序**（每库一次，按 library_id/doc_id 集合，不再逐篇）：
  1. 向量：共享 collection 用一次 `delete` + filter `library_id`；独立 collection 留到容器步骤；
  2. SQL：单事务按 doc_id 集合先删 FTS/citation_targets/tables/chunks/outlines/blocks/pages + `doc_blocks`/`document_segments`/`doc_block_corrections`/`canonical_vectors`（若存在），最后删 `canonical_documents`；
  3. `doc_catalog`：`DELETE ... WHERE library_id=?`；
  4. meta：`nodes`/`tree_node`/`libraries` 行；
  5. 文件：一次 `rmtree` 库根（`resolve_libraries_dir(lib)/<lib>` + 旧 `knowledge/libraries/<lib>`，去重）；
  6. 图谱：`GraphStore.delete_library`；
  7. 容器：按 P4-3 规则，`sqlite_file`/`collection` 引用计数=0 且非默认/内置组桶才删；
  8. registry 置 retired + `reload_scope_cache()`；对账 doc/point/file 计数=0。
- [ ] **前端**：`deleteLibrary` 返回 `{task_id}`；提交后关闭确认框、提示“后台删除中”，轮询 1–2s；进度面板显示 `向量/SQL/文件/图谱/registry` 与文档进度；行状态“删除中”并禁用操作；失败显示错误+重试；刷新页面用 `GET /libraries/{id}/deletion` 恢复。
- [ ] **文案**：共享桶确认写“只删本库数据，保留 `evals_corpus` 容器”；独立桶写“将删除本库 sqlite/collection”。
- [ ] **测试**：共享桶删 A 留容器/B 数据不动、A 的行/点/文件/catalog 清空；独立桶删净；引用计数含 retired；内置桶不删；9k 节点任务进度/重试/重启恢复。
- [ ] commit `feat(docs-core): 删库异步化 + 共享桶批量清理 + admin-web 进度`

### Task P4-1: 拆并「同组异构桶」保护（TDD）

**Files:** `services/docs-core/src/docs_core/kb_migrator.py:204-217`；Test：docs-core 迁移单测（对应现有迁移测试文件）

- [ ] `_check_destination_blockers` 增：源/目标同组但 `(sqlite_file, collection)` 不一致 → `MigrationBlocked("同组异构桶库不支持拆并（导入库为独立桶），请先联系维护迁移")`
- [ ] 测试：异构桶 → 拦；同桶 → 放行（既有用例不红）
- [ ] commit `fix(docs-core): 拆并拒绝同组异构桶（导入独立桶保护）`

### Task P4-2: 改组（编辑库）保护

**Files:** `services/docs-core/src/docs_core/docs_service.py:625-637`；Test：docs-core 对应单测

- [ ] 规则：库非空且新旧组的默认桶（`sqlite_file`/`collection`）不同 → 拒绝改组并提示（防止 F12 数据失联）；空库或同桶放行
- [ ] 测试覆盖三分支
- [ ] commit `fix(docs-core): 非空库跨桶改组拒绝（防数据失联）`

### Task P4-3: 独立桶容器删除（P4-0 worker 的收尾步骤）

**Files:** `services/docs-core/src/docs_core/library_delete.py`（P4-0）；Test：`services/docs-core/tests/test_delete_library.py`（附近文件）

- [ ] 仅当 `sqlite_file` 与 `collection` 的引用计数都为 0（含 retired 行）且非默认单文件/内置组桶 → 删 sqlite 文件 + 删 qdrant collection + 清库根目录壳；共享桶维持现状。
- [ ] 共享桶不删容器，只由 P4-0 清本库行/点/文件；`doc_catalog` 由 P4-0 清。
- [ ] 测试：独立桶删净；共享桶不动；retired 行引用不删；内置组桶不删。
- [ ] commit `feat(docs-core): 删库清独立桶（sqlite/collection/目录）`

### Task P4-4: 文档更新

- [ ] 改写 `docs/design-kb-export-ui.md`：v2 包格式/逐库小包/无同组警告/导入 UI 链接（或标注「被本计划取代」并新增 `design-kb-import-ui.md` 段落）
- [ ] `CHANGELOG.md`/README 摘要**留到发版时**按 AGENTS.md 契约写（版本号先报用户确认；`pnpm release` 前不手动改版本两处）
- [ ] 本计划完结后按 docs-cleanup 定式处置（结论进 CHANGELOG）

---

## 风险与边界

| 项 | 说明 | 对策 |
|---|---|---|
| qdrant recover 改名能力不确定 | v1 代码注释声称支持，未实测 | P2-0 卡点先验证（先试集合级 upload 路径）；兜底=临时名恢复+复制（P1-4 复用） |
| 源图谱历史悬空行 | 现网 `graph.sqlite` 与 default 切片实测 436 条（relations 112 + junctions 324）；FK ON 合并第一张联结表即回滚 | 合并连接 FK OFF + 事务内 `foreign_key_check` 对「目标原有 ∪ 包内自带」签名，新增违例回滚（P2-2） |
| HarveyLab `doc_catalog` 未进切片 | 核心目标 `lab-firm-full` 9,009 行 / 267 matter（10-20 实测）；`_DOC_TABLES` 12 表不含它 → 导出再导入后 `doc_search` 按 matter 枚举退化 | P2-0b 纳入 `_DOC_TABLES` + 同步 split 脚本 + 切片测试；DDL 已提交，可立即做 |
| evals 组文档树路径 | 导出写死 `knowledge/libraries/<lib>`；`lab-firm-full` 实际在 `evals/corpora/libraries` → `files/` 为空、9,009 条 file_path 全误报 | P1-8 用 `resolve_libraries_dir` 修正 + 两组夹具测试；先于 P2-0b/P2-2 |
| 大库删库 | 9,276 节点/4.1G 同步逐篇；前端默认 30s；`doc_catalog` 残留；共享容器误删风险 | P4-0 异步 + 批量 + 引用计数；P4-3 只删独立容器 |
| 图谱闭包切片的他库实体行 | 小包含归属他库 entity；目标已存同 `(name,library_id)` 异 id 行时 `OR IGNORE` 会丢实体 → 关系端点悬空 | P2-2 首版预检阻断；自然键重映射另立票；禁止静默 `OR IGNORE` |
| 导出临时 collection 残留 | 取消/断连可能留 `exp-tmp-*` | 导出启动清扫 + finally 删除 + 快照同删 |
| apply 中途进程重启 | 留半成品（文件/行已写）；冲突闸只拦已落 registry/index 的阶段 | P2-2 增清理命令/暂存标记；CLI/UI 输出暂存与清理指引，不做复杂回滚 |
| 大包上传 | 网关 body 限制/磁盘/断线；上传件 + spool + scratch 解包峰值约 3–4 份 | P3-3 **两层** nginx 放行（容器层入 git + 宿主机手工）；P3-1 前加磁盘余量预检；上传可重来 |
| 迁移启动时序窗（P1-5） | scan 闸后、单库切片/快照完成前迁移仍可启动 | 切片前逐库重闸，窗口缩到单库构建时长；残余窗口=极端并发下单库切片中段启动迁移 → 该库包判废重导 |
| 本地降级路无跨组扇出（F8） | 仅关 HTTP 走进程内路径时多库检索漏组 | 本票不改；代码注释与文档标注，另立票 |
| 嵌套 zip 流式实现 | Python zipfile 边写边套一层 | P1-1 先验证；兜底小 zip 落临时文件 |
| 版本/发版 | 铁律：push 与版本号需用户明确指令 | 见 AGENTS.md；本计划所有 commit 不自动 push |

**边界外发现（本票只记录，均建议另立票）：**
1. `kb_migrator._relabel_meta` file_path 改写恒不 match（F20）：相对化契约后按绝对前缀比较永不命中 → 迁移后重解析「源文件不存在」隐患；修法=改用 `to_data_relative` 口径比较。
2. 跨环境组织级同步自动化（不在本票范围）。
3. 本地降级路跨组扇出修复（F8）。

## 验收总表（全票做完）

1. 管理后台按组/按库导出 → 大 zip 内含每库小 zip；单库小 zip 可单独解出并单独导入。
2. 导入后每库落在独立桶（`knowledge/libraries/<lib>/index.sqlite` + collection=`<lib_id>`），归入指定组；检索（FTS/向量）、图谱查询（合并后逐表对账平、新增 `foreign_key_check` 违例=0，允许包内继承悬空）、溯源 `/pdf` 全通。
3. 全程零重解析（对账用既存产物计数即可证明：导出前后源库计数不变；导入后切片计数=manifest 计数）。
4. 拆并/改组/删库对独立桶库行为安全（拒绝或清理，无静默坏数据）。
5. v1 旧包不再支持；导入器只认 `schema_version=2`，旧包给明确升级提示。
6. `pytest tests/unit` + 相关 docs-api/docs-core 测试全绿；`vue-tsc -b` 过。
7. 大库删库异步完成、可重试；共享桶保留、独立桶按引用删除；`doc_catalog` 无残留。

## Self-Review 记录

- 覆盖：①大包套小包（P1-5 定版格式）✔ ②每库自包含+零重解析（P1-2/3/4 切片来源=现有产物）✔ ③图谱随包（P1-3/P2-2 落位）✔ ④独立桶落位（P2-2 映射表 + P4 保护）✔ ⑤CLI+UI 双通道（P2-3/P3）✔ ⑥v1 兼容已移出范围（2026-10-18 业主：旧包无人用；导入器只认 v2）✔。
- 已实测卡点：qdrant recover 改名（P2-0，可直接恢复成目标名）、嵌套 zip 流式（P1-1，py3.11/3.12 双端通过）——均已完成；当前硬卡点=图谱 436 条继承悬空，按第三轮修订的 FK OFF 基线口径处理。
- 评审修订（2026-10-17，全部已核实代码后落定）：P1-3 图谱切片改**闭包口径**（F17，含切片 `foreign_key_check` 硬断言，「B 库 0 行」断言只加 relations/artifacts）；P2-2 合并改**单事务+固定顺序+逐表对账+`foreign_key_check`**（F18）；reembed 定版 b 并 CLI/预检/前端三处文案收口（F19）；导出增 file_path 守卫（P1-5）与迁移中闸（`assert_library_not_migrating`）；P1-2 表清单改**直接 import `KbMigrator._DOC_TABLES`**（单一真相源）；P1-7 去掉估算误差门槛（FTS 体积非 chunk 线性）；P2-0 先试集合级 `POST /collections/<target>/snapshots/upload`。
- 评审修订·第二轮（2026-10-17）：P3-3 改**两层 nginx**（容器层 `docker/nginx/nginx.conf` 入 git 随 deploy + 宿主机手工报备，F21）；P1-5 增切片前逐库重闸（窗口见风险表「迁移启动时序窗」行）与 `embed_model` 导出开始固化（关 settings console 热替换窗）；FK 口径改「**对账为主、FK 检查为辅**」并据实测修正定式（F18：OR IGNORE 遇 FK 违例=报错回滚，非静默跳行）；P1-3 切片构建连接 FK OFF 纯拷贝，让检查拿完整诊断。
- 评审修订·第三轮（2026-10-18，开工前实测）：P2-2 图谱合并改 **连接 FK OFF + 事务内 `foreign_key_check` 基线对账**——现网 `graph.sqlite` 与 default 切片实测 436 条继承悬空（relations 112 + junctions 324），FK ON 第一张联结表 `principle_entities` 即回滚；只放行「目标原有 ∪ 包内自带」悬空，新增违例回滚。闭包实体同 `(name,library_id)` 异 `entity_id` 首版**预检阻断**，禁止 `OR IGNORE` 静默丢行；P2-2 增 `library_id`/`files` 路径安全闸与清理/磁盘预检。
- 评审修订·第四轮（2026-10-18，当时暂停，已被第五轮解除）：v1 导入兼容移出范围（旧包暂无人用；P2-3 清死代码、验收改“只认 v2”）；新增 **P2-0b** 合流 `doc_catalog`（10-18 时点 evals 组库 9008 行，`_DOC_TABLES` 未含）；当时决定 HarveyLab 收尾前不恢复 P2-2。
- 评审修订·第五轮（2026-10-20，复核 HarveyLab）：100 题报告 §4 保留 `doc_catalog`/`doc_search`/`doc_read`；未采纳 P1/P3/P0.5/P2.1/P2.2 与 Harness2 上游试跑，属链路实验，不影响存储契约。`doc_catalog` 已扩语义列；全表 21,802 行，其中 `lab-firm-full` 9,009 行/267 matter（10-18 为 9,008/266）→ **P2-0b 解锁，P2-2 可恢复**；P1/P2-1 已随 v0.3.0 发布。
- 评审修订·第六轮（2026-10-20，Harvey 库实测）：新增 **P1-8**——导出库根按组解析（evals 组=`evals/corpora/libraries`），当前写死 knowledge 会让 `lab-firm-full` 的 `files/` 为空、file_path 全误报；恢复顺序定为 **P1-8 → P2-0b → P2-2**。
- 评审修订·第七轮（2026-10-20，删库复盘）：`6f66b67d` 只修了节点/记录删除，整库仍同步逐篇 + 30s；新增 **P4-0** 异步任务 + 按 `library_id` 批量清 + `doc_catalog` 清理 + 共享容器引用计数；P4-3 收窄为“只删独立桶容器”。
- 未含（边界外）：见上「边界外发现」三条。
