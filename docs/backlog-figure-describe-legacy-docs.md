# 待办：存量文档图描述补齐 与 83 篇产物重建

> 状态：**阶段 1（存量图描述补齐）已于 2026-09-07 全部完成**（本地 26 + 生产 77 + 4 篇无图块无需做）。
> 溯源 PDF 视图：生产从未缺失（source/ 原 PDF 齐在快照里）；本地整目录倒灌完成后文件级同构（含源 PDF），
> 本地 DB 行级重索引（62 篇）按用户决策暂停为可选项。源文件离线备份在 `D:\AI\07智能建造\施工组织方案`。

## 起因

VLM 图描述功能上线前的存量文档没有图简介索引；部分文档解析产物在 2026-09-06 误删事故中于**本地**丢失
（生产侧产物当时已从 9-05 快照完整回灌，backlog 原记"双端丢失"不准确——只有本地丢了）。

## 完成记录（2026-09-06 22:00 – 2026-09-07 03:00）

### 阶段 1：存量 103 篇图描述全部补齐（A 类 26 + 生产独有 77）

| 类别 | 篇数 | 做法 | 结果 |
|---|---|---|---|
| 本地有产物、缺图描述（原"A 类"） | 22 篇 doc-* + 4 篇 v1-* = 26 | 本地逐篇 retry figure_describe（级联 fts/vectors/graph），VLM=dgx 唯一一次 GPU | 26/26 succeeded 零失败 |
| 仅生产有产物（原以为"双端丢失"） | 77 篇 doc-*（lib-261558be） | 生产侧逐篇 retry（VLM 直跑，~2 分钟/篇），本地无原料故不重复 | 77/77 完成（4 篇曾被 fts database is locked/读超时误记 failed，服务端实际全部完成，终验清零） |
| 产物在手但 jsonl 无任何图表块 | 4 篇 | 无需跑（避免白重建索引） | skipped |

- 两端重叠的 26 篇走**产物同步**：本地跑完 VLM 后把 `doc_blocks_graph.jsonl` scp 到生产，生产重触发时
  图描述阶段断点跳过（零 VLM 调用），只重建索引。
- 生产新生成的 77 份 jsonl 已倒灌回本地；**生产 77 篇的 `source/` 原 PDF 全数在服务器**（77/77，快照
  含源文件）——"溯源 PDF 视图降级"仅存在于本地；本地**整目录倒灌**（source+parsed 全量，约 4.2GB，
  经公网流式 tar 传输）+ 已完成源 PDF/文件级同构。**本地 77 篇零 VLM 重索引（DB 行级补齐）已暂停
  （2026-09-07，用户决策）**：本地→生产公网链路 ~0.55MB/s，逐篇远端 embedding 实测 ~18 分钟/篇，
  62 篇全跑完需 15h+，性价比低。已完成 15/77（加昨日 26 篇 A 类，本地覆盖 41/103），剩余 62 篇
  降级为可选项：链路快时 `--doc-ids` 续跑（state 断点续传）或走行级导出导入工具；文件级同构不受影响。
  **2026-09-09 更新：遗留项 A 已根治（Qdrant 切换，见下），批量重索引的 OOM 风险不再存在，可随时安全续跑。**
  另：2026-09-09 本地向量库已通过「服务器 Qdrant 快照恢复 + 8 篇本地独有/零覆盖文档重嵌」重建完毕
  （288/288 文档覆盖，222,315 条向量，检索与切换前基线 19/20 重合、top1 一致）。
- 工具：`scripts/open_ragbench/backfill_figure_descriptions.py`（本次升级：`--from-db` 自动筛队列/`--dry-run`/
  管理员 Bearer 轮询/`--token`/连接异常重试/兼容旧 python，commit `ea186da`）。
- 收尾日志归档：服务器 `data/recovery/fig_backfill_20260907/`（run77/runfix/chain 日志与清单）。
- 运维记录：生产临时管理员会话已删除；`/root/figbak` 临时工具目录已清理。

### 阶段 2 新发现：77 篇源文件全数在手 → 本地完整重建变为可行

- 用户目录 `D:\AI\07智能建造\施工组织方案`（262 文件）与 77 篇逐一匹配：**77/77 命中**
  （55 PDF + 22 DOCX，文件名=「PJ 编号_项目_公司_施工组织设计」）。
- 正确姿势不变：不删节点；源文件放回 `libraries/default|lib-261558be/documents/{doc_id}/source/`
  （文件名须与 nodes.file_path 一致），从 `raw_parse` 阶段按文档重跑，图描述与 render_pdf 自然产出。
- **本地重跑的代价警告**：见下方遗留项 A——批量重解析会把 4GB 生产机打成内存抖动半挂，本地无此约束，
  生产补解析必须挑低峰/分批，或先修遗留项 A。

## 遗留项（需排期）

- ~~**A. docs-api 常驻向量矩阵缓存在 4GB 生产机上撑不起批量重解析**~~（2026-09-07 凌晨实踩两次）：
  ~~每篇写库 → mtime 变 → 全表向量 JSON 重载（约 8 百 MB 级矩阵）→ 与解析峰值叠加 → 4GB swap 打穿、
  load>100、站点/sshd 假死，内核 OOM 杀 uvicorn（dmesg：anon-rss 2.87GB / 3.1GB 各一次）自愈后循环。~~
  **✅ 已于 v0.2.41（2026-09-08/09）根治**：向量引擎切换 Qdrant（`DOCS_VECTORSTORE_PROVIDER=qdrant`），
  客户端矩阵缓存整体移除（无双进程内存矩阵、无 mtime 全量重建锁），写入为 Qdrant 侧 HNSW 增量；
  生产实测切换后可用内存 648MB→2.4GB、启动守卫 604s→4.8s，批量重解析的 OOM 链路不复存在。
  阶段 2「本地/生产重跑代价警告」同步解除（剩余瓶颈仅为公网 embedding 链路速率）。
- ~~`SQLiteVectorStore.get_existing_dimension()` 以 rowid 最后一行为全库期望维度~~（已修，两段式）：
  commit `83797be` 改为全表多数表决 + upsert 默认拒写异构维度——但表决被 embedding_provider 在模块
  import 期调用，5.3GB/21 万行库单次表决 294s，容器启动被拖 15+ 分钟（2026-09-07 两次部署实踩 502）；
  commit `4dedae7` 根治：index_meta 表持久化期望维度，稳态 O(1) 免扫描，meta 缺失才跑一次表决落库，
  `strict_dimension=False` 迁移路径清 meta 重算；生产存量库已离线种 meta（1024 维）。同批 6+5 测试全绿。
- **B. docs-api import 期/启动热路径不得跑无界全表查询**（4dedae7 根因教训）：embedding_provider 模块级
  初始化即触发维度探测，历史如此、直到表决引入才暴露量级。同类 import 期 DB 调用建议后续排查
  （aichat-api 的预热是显式后台任务，无此问题）。
- 拒答重答守卫对"结构上根本答不了"的问题（如引用不存在的"图 N"索引）多烧一轮检索（+20 秒级），未动。
- ~~服务器 `knowledge_index.sqlite.bak-recovery-*`、`.pre-merge-*` 等备份共约 12GB（单文件 2.4GB 级），
  2026-09-13 快照清理期后择机删除（当前留作事故回溯，勿提前清）。~~ **已于 2026-09-08 清理完毕**
  （用户批准）：index bak 2.3GB + meta/parse_records/users 小 bak 全删，另回收废弃 chroma 遗留 1.1GB；
  `data/recovery/` 实测仅剩 32K 日志档案。

## 事故档案索引

恢复全过程工具与备份：`data/recovery/`（doc_list / vectors_done / refill / reembed / vec_sync 导出，
快照 `snapshot-20260905.sqlite` 建议 2026-09-13 后清理）；数据库备份 `*.bak-recovery-20260906*`（本地）与
`*.bak-recovery-20260906pm`（生产）。防护修复见 commit `8378e13`（clean-orphaned 以数据库实况判定 + 批量护栏）。
图描述补跑档案：生产 `data/recovery/fig_backfill_20260907/`。
