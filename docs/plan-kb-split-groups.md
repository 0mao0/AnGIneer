# 知识库拆分计划：库组注册表、多库问答、页面化拆合（2026-10-03）

状态：规划（未开工）。本文档承接 docs/plan-retrieval-speedup-v3.md 的 R5 结论与容量规划（1 万本报告 × 100 页 ≈ 400 万向量＋20G 正文），定义知识库存储的分组拆分、多库问答改造、页面化拆分/合并、data/ 目录归位四件事。

---

## 一、分组方案（按用途与更新节奏，不按 benchmark 逐个拆）

| 组 | sqlite（正文＋FTS） | qdrant collection | 内容 | 特性 |
|---|---|---|---|---|
| 生产组·规范 | knowledge_standards.sqlite | standards | 规范库（现 default 库主体） | 大、静态、查询性能敏感 |
| 生产组·施组 | knowledge_dredgeai.sqlite | dredgeai | 施组库（规划） | 大、低频更新 |
| 评测组（合一） | knowledge_evals.sqlite | evals | financebench / omnidocbench / openragbench / GDP 等全部评测语料，内部靠 library_id 区分 | 小、常重灌、只在评测时用 |

分组原则：**按用途与更新节奏分组，组内靠 library_id 区分**。
- 生产组按业务域各一份：查询只碰本库索引，页缓存局部性最好
- 评测组合一：生命周期一致（一起备份/重建/清理），避免按 benchmark 拆太碎（每 collection 固定开销 MB 级，份数多了才亏）
- 边界规则：评测组总量 >100~150 万条、或单体 benchmark 涨到几十万条时，拆出独立成对

## 二、库组注册表（四件事共同的地基，先做）

新增注册表 `library_registry`，**落独立单文件 `data/registry.sqlite`**：不放任何组内 sqlite（knowledge_index 拆完自身就在组文件里，注册表存进去是鸡生蛋），不做进程缓存（新库不重启不可见的老病，必须读穿）。

| 字段 | 说明 |
|---|---|
| library_id | 库标识（现 ScopeContext 用的那个） |
| group | 组名：standards / dredgeai / evals / …（新增组=新登记一行） |
| sqlite_file | 该组的知识库文件路径 |
| collection | 该组的 qdrant collection 名 |
| status | active / migrating / retired |

- 检索、入库、评测、备份全部**从注册表解析存储位置**，代码里不再按路径约定猜位置（`QDRANT_COLLECTION` 全局单配置退役为回退默认值）
- `/knowledge/libraries` 列表接口**注册表直出**（名称/组/状态随注册行携带，带 `group` 字段），不做「逐个打开组文件汇总」——展示接口不能开 N 个 sqlite
- 没有这张表，多库问答、页面化拆合和目录归位都没有挂靠点——所以它是阶段一

## 三、问题 1：多库勾选问答（前端＋后端）

现状：问答请求只带单库（`QueryRequest.library_id: str = "default"`），前端库选择器单选。

### 3.1 前端改动

| 位置 | 改动 |
|---|---|
| user-web 聊天输入区 @ 库选择器 | 单选改**多选**（chip 形态，克隆现有 antd select multiple 模式；上限建议 ≤5 库，防 token 失控） |
| 会话模型 | 会话绑定的库集合随消息走；旧会话单库自动兼容读为单元素列表 |
| admin-web | 评测页不受影响（题集自带 doc_ids/库范围） |

### 3.2 后端改动

| 层 | 改动 |
|---|---|
| API | `QueryRequest.library_id` 增补 `library_ids: List[str]`（旧字段保留兼容，单选=单元素） |
| ScopeContext | `library_id: str` → `library_ids: List[str]` |
| 检索 fan-out | 按注册表把勾选的库按**组**分发：同组=同文件/同 collection 内多 library_id 过滤（IN 查询）；跨组=各自查一组存储再合并。勾 3 库最少只打 1~3 次底层查询，不是 3 倍成本 |
| **跨源融合（关键设计）** | dense 向量分数同空间可直接比；**sparse BM25 分库后分不可比**（各库 IDF 统计不同）——跨库合并用 **RRF（倒数排名融合）**：各源各取 top-K，按排名折算合并，再统一 rerank。选 RRF 不选分数归一化：对分布漂移稳健、无参数 |
| rerank／引用 | 候选合并后进统一 rerank（0.6B 分数跨源天然可比）；引用标记仍由单 Allocator 顺序编号（K1、K2…），多库不冲突 |
| 上下文预算 | 合并后仍截 top 20 进上下文。**待定参数**：勾 N 库时是否每库保底条数（如每库 ≥5）或 top_n 随库数放大——防「勾越多、单库证据越稀」 |

### 3.3 体验验收

- 勾选两库提问，证据能同时命中两库，引用编号连续、来源库标注正确
- 单库勾选行为与现状完全一致（回归线）
- 多库查询检索段 p90 ≤ 单库 × 1.5（fan-out 并行 + RRF 合并的开销上限）

## 四、问题 2：拆分/合并页面化（admin-web）

回答：**能做，且应该做成「预览 → 后台任务 → 原子切换 → 保留回滚」四步的管理页操作**，而不是一次性脚本。交互克隆现有知识库页的行内操作模式。

### 4.1 两个操作的定义

| 操作 | 输入 | 行为 |
|---|---|---|
| 拆分 | 源库 ＋ 拆分键（按文件夹/标签/勾选文档）＋ 新库名 | 把源库部分文档迁移到新库（同组内：同文件换 library_id；跨组：跨文件跨 collection 搬运） |
| 合并 | 源库 A、B（同组）＋ 目标库名 | A、B 全部文档迁入目标库，A/B 置 retired |

### 4.2 安全机制（页面化的前提，缺一不可）

1. **预览**：执行前先出计数 diff（每库/每文件夹块数、向量条数），用户确认才执行
2. **后台任务**：迁移是长任务（qdrant scroll＋upsert，58 万条约小时级），带进度条、可取消；页面只下发任务，不阻塞
3. **原子切换**：迁移期间源库照常可读；全部对账通过后，注册表一次翻转 status 指到新位置
4. **回滚窗口**：源数据保留 7 天再物理删除；期间一行命令回退
5. **权限**：仅 admin；操作留审计（谁、何时、拆了什么、对账结果）

### 4.3 技术要点

- qdrant 侧迁移用 **scroll＋upsert，不重新嵌入**（向量原样搬，省 GPU 与数小时）
- sqlite 侧 INSERT SELECT（同文件内=改 library_id；跨文件=跨库 ATTACH 搬行）
- 迁移幂等：中断重跑不产生重复（以 block id 为去重键）
- 拆分/合并只动**数据与注册表**，不动代码与镜像——这是页面化的可行性前提

## 五、data/ 目录整理（终态与搬家映射）

原则：**域＝生命周期单位＝搬迁单位；位置由注册表说，不由路径约定说。** 现状两笔债：评测语料解析产物与索引挤在生产库内（同一 sqlite、同一 collection，`knowledge_base/libraries/` 生产库与评测库 12 个混列）；评测原件散在 data 根四个目录。

```
data/
│ ├─ registry.sqlite                    ← §二注册表，全局独立文件
│ ├─ knowledge/                         生产知识域（一年动一次；备份一次；整体搬 DGX 的就是它）
│ │   ├─ groups/standards.sqlite、dredgeai.sqlite    （阶段二拆出的组文件：正文＋FTS＋目录层表）
│ │   ├─ graph.sqlite、parse_records.sqlite          （收编：图谱库现孤悬 data 根；parse_records＝上传台账）
│ │   └─ libraries/<library_id>/                     （解析产物，目录名不动，仅换爹）
│ ├─ evals/                             评测域（周周重灌；永远留部署机）
│ │   ├─ datasets/、nightly/、baseline/、probes/、replay/、parse_regression/ （现有，不动）
│ │   ├─ originals/<bench>/             语料原件（收编 data/financebench、gdp_pdf、officeqa、open_ragbench）
│ │   ├─ groups/evals_corpus.sqlite     评测语料正文＋FTS（阶段二新文件；命名刻意避开成绩库 evals.sqlite）
│ │   ├─ corpora/libraries/<id>/        评测语料解析产物（与 knowledge/libraries 同构，路径解析按注册表切换）
│ │   └─ evals.sqlite                   成绩库维持现名（题集金标＋run 明细，result_store 引用路径零改动）
│ ├─ platform/                          运行时域（chat/users/api_keys/sops——只改路径常量，数据不动）
│ ├─ qdrant/                            单实例单目录，组体现在 collection 名（standards/dredgeai/evals）；
│ │                                     分组备份/搬运＝collection 级快照 API，**不做两套 qdrant**（内存不允）；
│ │                                     开发机现用命名卷 qdrant-dev-data，阶段一改 bind mount 到本目录，两端同形态
│ ├─ _retired/<日期>/                   §4.2 七天回滚窗口的源数据滞留区，一眼可删
│ └─ ops/、scratch/                     维持现状
```

**搬家映射**

| 现位置 | 去处 | 动作性质 |
|---|---|---|
| knowledge_base/libraries 里的评测库（omnidocbench、lib-officeqa、lib-cf08e666…） | evals/corpora ＋ evals 组文件 ＋ qdrant evals collection | 阶段一二顺路完成，不是额外工作 |
| data/financebench、gdp_pdf、officeqa、open_ragbench | evals/originals/ | 纯 mv，同步 paths 解析与 .env 引用 |
| knowledge_graph.sqlite、parse_records.sqlite | knowledge/ 下 | 各改一处路径解析 |
| chat/users/api_keys/sops | platform/ | 改路径常量 |
| knowledge_base/ → knowledge/ | 目录改名 | 服务器 mv ＋ compose 挂载核对 ＋ 容器重建 |

工作量归位：大搬＝阶段一二本身；本节净新增只有 registry.sqlite 落位、几个 mv、若干路径常量。

**页面显示分组（评测语料不进生产页面的配套）**：admin 知识库管理页（`KnowledgeStats` 顶部 `LibrarySelect`）加组 segment（生产/评测），评测组操作能力与生产完全一致（重灌/解析/体检/删除都可用）；user-web @ 库选择器只列生产组；题集卡弹层加「语料库」一行跳转知识库页。组判定全在后端（注册表直出 `group` 字段），前端只过滤展示。

## 六、阶段与验收

| 阶段 | 内容 | 验收 |
|---|---|---|
| 一 | 注册表落 `data/registry.sqlite`（列表接口注册表直出带 group）＋ qdrant 按组拆 collection（迁移现 58.4 万条：规范→standards、评测语料→evals，scroll+upsert 不重嵌入）＋ 开发机 qdrant 命名卷改 bind mount `data/qdrant` | 全量对账 counts 零差异；保温探针曲线无回归；一行配置可回旧 collection；运行中新增注册行**不重启即可检索**（读穿） |
| 二 | sqlite 按组拆文件（连接注册、迁移、备份脚本同步改）＋ data/ 目录归位（§五：三域落位、originals 收编、graph/parse_records 收编、admin 组 segment、user-web 选择器只列生产组） | 各组文件对账零差异；入库与查询互拖消失（重灌一个评测库、规范库查询延迟不变）；知识库页只见生产组、切评测组可完整操作 |
| 三 | 多库勾选问答（前端多选＋后端 fan-out＋RRF） | 3.3 节三条验收 |
| 四 | admin 拆分/合并页 | 完整演练一次拆＋一次合并：预览数字=实际数字、可取消、可回滚、审计完整 |

## 七、风险清单

| 风险 | 对策 |
|---|---|
| BM25 跨库分数不可比 | RRF 融合（已定，见 3.2） |
| 多库勾选摊薄单库证据 | 每库保底条数或 top_n 放大（阶段三定参数） |
| 迁移中断 | 幂等设计（block id 去重），源不动、目标可删重跑 |
| collection 碎片化 | 库组数量控制在个位数；评测组设总量拆分阈值 |
| 历史会话绑旧单库 | 单库读作单元素列表，零迁移 |
| 阶段三改 scope 语义波及会话图计划（`conv_graph_*` 原主键写死 `scope_hash`） | ✅ **已收口（2026-10-04）**：阶段三 Phase B–E 落地后，`req-blackboard-conversation-mode.md` §5 按 **D6** 改版——会话身份 = `(owner_key, session_id)`，`scope_hash`/`library_ids_json` 降为节点来源列；原「预留过渡列」作废。两份文档已同步（BB §5/§5.1、`plan-blackboard-arms.md` §7） |
| qdrant 多 collection 固定开销 | 个位数 collection 无碍（每份 MB 级）；不拆几十个 |
| 目录改名与服务器侧引用漂移（.env、备份脚本、compose 挂载） | 动手前全库 grep 列全引用点一处清单改齐；改后重启＋检索探针复验才收工 |

## 八、与 DGX 部署的关系

分组拆分**不依赖** DGX 落地，但拆完即具备整体迁移条件：生产组（一库一文件一 collection）搬 DGX＝拷文件＋快照；评测组（小、常动、评测在部署机跑）留腾讯云零隧道往返。两边按组独立搬运、独立回滚。

## 九、待用户确认的决策点

1. 多库勾选上限（建议 ≤5）
2. 多库时的证据分配规则（每库保底 vs 纯排名，阶段三定）
3. 拆分键的形式（按文件夹为主？还是允许任意勾选文档集合）
4. 施组库库名（dredgeai 为占位）
5. 命名（10-03 倾向已定）：成绩库 `data/evals/evals.sqlite` **维持现名**（题集金标＋run 明细都在其中，改名零收益、result_store 引用还省一处）；评测语料组文件新起名为 `evals_corpus.sqlite`。初稿提议的 `runs.sqlite` 已否——该库不只装 runs，名字丢信息。
