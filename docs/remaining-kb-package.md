# 语料包导入导出：剩余事项

**日期：** 2026-10-21（P3-4 两项演练当日收口；2026-10-25 复核发布状态；2026-10-28 生产真包复测完成）
**当前状态：** 复测项全部收口（含 2026-10-28 生产真包上传复测）；闭包实体「首版阻断」问题已按 **A 方案**（图谱改一库一文件）施工完成，闸门实体比对整段移除——施工单见 [plan-graph-per-library-split.md](plan-graph-per-library-split.md)。
**主计划：** [plan-kb-per-library-package.md](plan-kb-per-library-package.md)

---

## 1. 待办总表

| 优先级 | 事项 | 状态 | 说明 |
|---|---|---|---|
| P0 | P3-4 真实检索探针 | **已完成** | 真实包 `system-20261018.zip`（9 文档/701 chunk/973 向量）导入临时根：FTS 20 命中、向量 20 命中、`doc_title` 正确、PDF 200 |
| P0 | P3-4 apply 中途 kill 演练 | **已完成** | 2s 处杀 docs-api：任务表丢、暂存包留、半成品 default 落盘、重导被 index 冲突拦住；清理 CLI 已补并验证 |
| P0 | P3-3 宿主机 nginx 放行 | **已放行 + 已复测**（2026-10-28） | 真实 body 三连测：36.9MB 真包、41.3MB 真包、220MB 非法 zip 全部经 `https://angineer.cn` 过 nginx→frontend→docs-api 全链路，无 413；详见 §10 |
| P1 | P4-4 CHANGELOG/README/版本 | **已随 v0.3.2 / v0.3.3 发布** | `b16457b1`（清理 CLI/404 指引）在 v0.3.2，`78f34597`（存量补齐记录 + 镜像补脚本 + CHANGELOG 条目）在 v0.3.3 |
| P1 | **闭包实体重名放行策略**（复测新发现） | **待拍板** | 预检对「同 (name, library_id) 不同 entity_id」按 `首版阻断` 处理；docstring 设计是「告警不阻断、对账兜底」，但 `_merge_graph` 只 `INSERT OR IGNORE` 无按名合并——放行会产出重复实体，维持阻断则跨环境导入图承载语料必被拦。见 §10 |
| P2 | 克隆导入（同实例并存） | 可选，未立项 | 需全量 ID 重映射，不是加 `(2)` 后缀 |
| P2 | 测试产物清理 | **已清理** | `p3-ui-target*`、`p2-5`、`p2-cli-target`、`p2-cli`、`qdrant-local` 已删；保留 `p3-5-probe` 证据（约 25MB） |
| P2 | 宿主机大文件复测 | **已完成**（2026-10-28 生产实测） | 220MB 非法 zip → 400「上传内容不是合法 zip」（39.5s、无 413、暂存自清）；与本地 10-21 结论一致 |

---

## 2. P3-4：真实检索探针（已完成 2026-10-21）

**结论：** 导入库可被 FTS 与向量两路召回，`metadata.doc_title` 取到 meta 节点标题，源 PDF 可下载。

**环境：** 本地复核；qdrant v1.19.0（Windows 构建，`data/scratch/qdrant-local/`）空库启动；
临时数据根 `data/scratch/p3-5-probe/target`（先建 meta 表骨架，避免 docs-api 启动自动建 `default` 撞库）；
包用 `data/scratch/kb-pkg-p1-7/system-20261018.zip`（v0.3.1 前真实导出：9 文档、701 chunk、973 向量、embed=`qwen3-embedding`）。

**步骤与实测：**

1. `python scripts/kb_corpus_import.py --package system-20261018.zip --group system --apply` → 应用完成；
   `knowledge/libraries/default/index.sqlite` 701 chunk、qdrant collection `default` 973 点（dim 1024）、registry 行 `active`。
2. `POST /api/knowledge/internal/retrieve`（`library_id=default`, `top_k=5`, `mode=text`）：
   - 查询「船闸」：`debug.sources.dense.input_hits=20`、`sparse.input_hits=20`（FTS 与向量各命中）；
   - 5 条 item 的 `metadata.doc_title` 均为 `JTJ 305-2001 船闸总体设计规范.pdf`；
   - `stage_times`：dense 4.67s / sparse 0.06s / fuse 0.002s（首次查询含 embedding 冷启动）。
3. 长查询（正文首段 24 字）同样 dense/sparse 各 20 命中，首条 title/正文一致。
4. PDF：`GET /api/knowledge/documents/doc-a945b15d/download?kind=pdf` → **200 / application/pdf / 1,638,413 B**。
   - 文档里写的 `/api/knowledge/documents/<doc_id>/pdf` **不存在（404）**；
   - `/api/v1/documents/<doc_id>/pdf` 存在，但对「源文件本身是 PDF」按设计返回 404（`原始文件为 PDF，用户已有源文件，无需下载`）。
5. 旁证（非阻断）：`POST /internal/doc-search` 返回的 `docs[].title` 仍是 `doc-*` id——该包导出时组 sqlite 无 `doc_catalog` 表，
   导入侧没有 title 可读；检索主链的 `doc_title` 注入走 meta `nodes`，不受影响。

**证据文件：** `data/scratch/p3-5-probe/probe-result.json`、`probe_pdf_auth.py`。

---

## 3. P3-4：apply 中途 kill 演练（已完成 2026-10-21）

**结论：** 强杀后进程内任务表必然丢失（`status`/`DELETE` 均 404），暂存包与半成品库落盘；
再次导入被 index 冲突闸拦住，提示明确但**没有 API 清理通道**——已补 CLI。

**演练（临时根 `kill-target`，先 CLI 导入 `lib-import-test2` 当种子库，避免 docs-api 自动建 `default`）：**

1. 起 docs-api（8799）→ 登录 → 上传 `system-20261018.zip` → `POST /imports/<id>/apply`（后台线程）；
2. apply 受理后约 2s `Stop-Process` 杀 uvicorn；
3. 现场：
   - `scratch/imports/imp-27c9e4ec4674/package.zip` 保留（36,899,939 B）；
   - `knowledge/libraries/default/` 有 index.sqlite + 部分文档树；
   - registry **没有** default 行；meta 已写 `libraries` 1 行、`nodes` 3 行、`tree_node` 7 行；graph 已并入 428 实体/339 关系；
   - qdrant 尚无 `default` collection（kill 落在 vectors 阶段，registry 之前）。
4. 重启 docs-api：
   - `GET /imports/<id>/status` → **404**；`DELETE /imports/<id>` → **404**（任务表内存态）；
   - 库列表出现**幽灵 `default`**（group/collection/status 为空）——meta 行已写、registry 未写；
   - 重新上传同一包 → **400**：`[default] 目标已有 index.sqlite: .../knowledge/libraries/default/index.sqlite`。
5. 清理通道：新增 `scripts/kb_corpus_import_cleanup.py`（默认 dry-run，`--apply` 才删）：
   - 孤儿暂存：`--scratch` 清 `<data 根>/scratch/imports/*`；
   - 半成品库：registry 无行、但有目录/meta 行的库，删目录 + meta 行（nodes/tree_node/libraries）+ 解析台账 + 图谱行 + 同名 qdrant 集合；registry 有行的库（含 retired）一律不动。
   - 本演练实测：清掉暂存 36.9MB 与半成品 `default`（meta 3/7/1、graph 428/339、台账 3）后重启，库列表只剩种子库，
     再上传同一包 → **200 预检通过**，可正常 DELETE 暂存。
6. 提示补强：`import_routes._task_or_404` 的 404 文案现在会说明「进程重启任务表丢失」并指向清理 CLI。

**已知边界：** 半成品库在清理前会以空 group/collection 出现在列表；apply 不落事务，kill 点不同残留不同（files/index/graph/meta/vectors/registry 顺序见 `corpus_import_apply.py`）。

---

## 4. P3-3：宿主机 nginx（已放行 2026-10-21）

容器层已改：[docker/nginx/nginx.conf](../docker/nginx/nginx.conf) 的 `^~ /api/knowledge/imports/`。

宿主机文件：`/etc/nginx/ai-proxy-locations.conf`（不在 git）。

**已执行（用户批准后）：**

1. 备份：`/etc/nginx/ai-proxy-locations.conf.bak-20261021-imports`；
2. 在 `location /` 之前插入（第 91–103 行）：

```nginx
    location ^~ /api/knowledge/imports/ {
        client_max_body_size 0;
        proxy_request_buffering off;
        proxy_pass http://127.0.0.1:8080;
        proxy_buffering off;
        proxy_cache off;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
    }
```

3. `nginx -t` 通过 → `systemctl reload nginx`（is-active=active）。

**验证（不做业务写入）：**

- 改前基线：`POST /api/knowledge/imports/upload` + `Content-Length: 300000000`（无 body）→ **413**；
- 改后同一探针：nginx 不再 413，请求被转发（8s 内无响应，因等待声明的 body；服务器回环 HTTP/2 同请求得 400）；
- 小请求仍 `401`（`{"detail":"Missing X-API-Key or session token"}`），证明 **host → frontend 容器 → docs-api 两跳都通**；
- 真实小包/>200MB 包各上传一次**已完成（2026-10-28，见 §10）**：三次真实 body 经公网全链路实测，nginx 无 413、暂存自清；
- **本地补测（2026-10-21，不经 nginx）**：本地 docs-api 8790 上传 210MB 非法 zip → `400 上传内容不是合法 zip`（1.3s，无 413，暂存自动清）；再传真实小包 `lib-import-test2.zip` → `200 previewed`，`DELETE /imports/<id>` → 200。证明 app 侧大 body 与上传/预检/清暂存链路正常；生产仍差真包一次。

**回滚：** `cp -a /etc/nginx/ai-proxy-locations.conf.bak-20261021-imports /etc/nginx/ai-proxy-locations.conf && nginx -t && systemctl reload nginx`。

---

## 5. P4-4：发版收尾

- CHANGELOG/README 摘要**留到发版时**写，按 AGENTS.md 契约；
- 版本号先报用户确认，不自行定号；
- `pnpm release` 前不手改 README/package.json 版本；
- 不自动 tag、不自动 push。

发版前建议至少完成：真实小包/大包各上传一次（需要生产管理员会话）。检索探针、kill 演练、宿主机 nginx 已于 2026-10-21 通过。

---

## 6. 可选：同实例克隆导入（未立项）

需求：旧库保留，新库在同一后台并存。

不是改 `library_id` 后缀即可：

- 节点 `nodes.id`、`doc_id`、`chunk_id`、图谱 `entity_id/relation_id` 都是全局主键；
- 文件路径、meta、graph、qdrant payload/collection 都要跟着重映射；
- 需要新命令/选项（如 `--as-library-id`）+ 小包测试 + default 包验证。

**建议：** 除非“同一后台并排两份”是硬需求，否则不做；迁移/恢复用空 data 根/另一环境即可。

---

## 7. 清理与收尾

- `scripts/kb_corpus_import_cleanup.py`：导入残留清理（孤儿暂存 + registry 无行的半成品库），默认 dry-run；
- `data/scratch/p3-5-probe/`：本轮证据（`probe-result.json`、`kill-restart.json`、导入临时根 `target`）；`kill-target` 已在验证后删除，可整目录删；
- `data/scratch/qdrant-local/`：本地探针用 qdrant（bin + storage），仅开发机，勿进镜像/勿提交；
  启动时除 `QDRANT__STORAGE__STORAGE_PATH` 外还要设 `QDRANT__STORAGE__SNAPSHOTS_PATH`（默认落当前目录 `snapshots/`，曾把 11MB 快照写进仓库根）；
- `data/scratch/p3-ui-test/lib-import-test2.zip`：有效测试包，可留可删；
- `data/scratch/p3-ui-target*`、`p2-5`、`p2-cli-target`：临时导入根，确认后可删；
- `lib-import-test` / `lib-import-test2` 的 `retired` 审计行：列表不显示，可留审计；确认不再恢复可手工清；
- docs-api 是 detached 进程（不是受管 job），日志在 `data/logs/docs-api-import.log`；
- 不要提交 `data/`、`.dsh-figures/`、Harvey/时间维度那条线的未提交改动。

---

## 8. 已知边界（当前版本）

- 导入包内 `files/` 根必须与目标组 `libraries_dir` 一致（knowledge 包用 knowledge 组，evals 包用 evals 组）；
- 不支持 v1 目录/tar 包；
- 不支持 reembed，模型不一致直接阻断；
- 普通“新建库”仍走组共享桶；只有 v2 包导入走独立桶；
- 导入不自动合并/覆盖同名库；同 `library_id` 的 retired 行可被 restore 替换；
- 应用阶段不可取消，失败保留暂存；**apply 无整体事务**：进程被杀会留半成品，任务表随进程消失，只能用清理 CLI 收尾；
- **时间检索随包走的前提是导出前回填**：`doc_date/date_source/date_confidence` 在 `doc_catalog` 里，切片整表带走；
  但源库没回填时包内为空，源库没跑过懒 ALTER 时包内连三列都没有（导入侧只补空列）。导入不保留 mtime，
  导入后再跑 `backfill_doc_dates.py` 会把 mtime 档写成导入时间——回填必须在导出前；
- 上传支持 multipart，不支持断点续传；
- 跨环境导入带图谱的语料包已不再被拦（2026-10-28 图谱改一库一文件后实体闸移除，见 §10）；剩余口径：跨库同名实体自拆分起各库各存（含拆并撞名时源行保留）。

---

## 9. 相关提交

- P2-3 CLI：`31e7a30a`
- P3-1 路由：`4ccb8d01`
- P3-2 UI：`37d8311a` / `c25cdc29`
- P3-3 容器 nginx：`d68f92c2`
- P4-0 删库：`00817fdf` / `21b90628`
- P4-1/P4-2/P4-3：`b4203b04` / `475376ab` / `2508774a`
- P4-4 文档：`ac1535f4`
- 台账/删库补丁：`98959483` / `b858e2c3`
- 删库 Windows 锁/重试：`34183442`
- retired 同 id 恢复：`d02d8c04`
- P3-4 断点测试：`66ff9ada`
- 清理 CLI `scripts/kb_corpus_import_cleanup.py` + 单测、404 文案补强：`b16457b1`（v0.3.2）

---

## 10. 2026-10-28 生产真包复测（含新发现）

**会话通道：** 免改密铸会话（`docker exec` 进 docs-api 容器 `create_session(admin)`，不动密码、不清既有会话，测完即 `delete_session`）。

**三次真实 body 上传（全部经 `https://angineer.cn` 公网链路：宿主 nginx `^~ /api/knowledge/imports/` → frontend 容器 → docs-api）：**

| # | 包 | 结果 | 结论 |
|---|---|---|---|
| 1 | `system-20261018.zip`（36.9MB，内容已在生产） | 400 冲突闸拒绝：`library_id 已存在: default` + 3 个节点 id | 传输链 + 上传落盘 + 预检全链路工作正常，同内容重导按设计拦下，暂存自清 |
| 2 | `standards-20261028.zip`（41.3MB，`std-municipal` 本地新导出，5 docs/820 chunk/1185 向量，ID 与生产零冲突） | 400 `闭包实体冲突，首版阻断`（5 条重名，逐条标注「不阻断；按对账/merge 处理」） | **新发现，见下** |
| 3 | 220MB 非法 zip | 400「上传内容不是合法 zip」（39.5s，无 413，暂存自清） | 大 body 过 nginx 无 413，与本地 10-21 结论一致 |

**新发现：闭包实体「首版阻断」与设计意图相悖，跨环境导入图承载语料必被拦。**

- 判据（`corpus_package.check_conflict_gate` docstring）：小包实体**归属他库**（闭包切片天然带上如 `default` 的共享种子实体）且与目标同 `(name, library_id)` 不同 `entity_id` → **告警不阻断**，对账 + FK 检查兜底；逐条 warning 文案也自称「不阻断；按对账/merge 处理」。
- 实现（`corpus_import_apply.py:638`）：`if gate["warnings"]: raise BundleError("闭包实体冲突，首版阻断: …")`——warning 一律拦死。
- 放行为什么现在不安全：`_merge_graph` 是按主键 `INSERT OR IGNORE`，**没有按名合并**——放行会产出重复实体（如「船舶荷载」×2）。v1 阻断是安全兜底，但后果是：只要目标实例图谱里已有任何同名词实体（生产 `knowledge/graph.sqlite` 是全局读取、不分组），任何跨环境导出的工程语料包都过不了预检。**空 data 根恢复 / 无图谱语料（法律域种子门控 `graph_entities=0`）不受影响。**
- **处置（2026-10-28 用户拍板 A 方案、「不该全局一张表」）：图谱改一库一文件，已施工完成**（施工单 [plan-graph-per-library-split.md](plan-graph-per-library-split.md)）——导入实体闸整段移除、包内图谱整文件落位、跨环境导入带图谱语料不再被拦；原备选 ②（维持阻断收窄为「空根恢复」）作废。

**复测证据与遗留物：** `data/scratch/kb-pkg-retest2/standards-20261028.zip`（41MB 无冲突测试包，拍板后复测直接可用，可留可删）；服务器 `data/scratch/imports/` 三连测后为空；临时会话已注销（`DEL_SESSION: True`），生产侧临时文件已删。
