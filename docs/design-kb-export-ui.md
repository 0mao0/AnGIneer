# 知识库语料包导出（管理后台）设计

**日期:** 2026-10-09
**业主定版决策：** 纯流式下载（不落盘）｜包内容固定 = CLI 默认｜可勾选库 + 未全选明示警告
**上游：** `docs/plan-standards-kb-corpus-package.md`（语料包通道本体）｜`scripts/kb_corpus_export.py`（现有 CLI）

---

## Goal

管理后台「知识库」页头部（加号后）加一个「导出语料包」按钮：弹框选集合与库 → 服务端边打包边推流 → 浏览器落成 zip。全程有进度条，可取消。

## 决策与其理由

| # | 决策 | 理由 |
|---|---|---|
| D1 | **纯流式**，服务端不落盘 | 业主拍板。7.75GB 单趟读出即出网；服务端零残留 |
| D2 | 包内容**固定** = CLI 默认（含向量快照、砍 `mineru_raw`/`popo`） | 与交付给 DredgeAI 的包同口径；少一层误用面 |
| D3 | 库**可勾选**；未全选时红字警告 | 同组共用 sqlite（FTS/graph 无法拆分），取消勾选不改变 sqlite 内容，必须让操作者知情 |
| D4 | **zip** 而非 7z | zip 是 Python 标准库；内容大头（PDF/图片/sqlite）已压过，7z 收益小且要加依赖重建镜像 |
| D5 | 压缩方式 **ZIP_STORED**（仅打包不压缩） | 省 CPU 与时间；对已压缩内容无收益 |

## 为什么流式反而更快

现有 CLI 是四趟 IO：staging 拷贝（读+写）→ sha256 全扫（读）→ zip（读+写）。
流式只需**一趟**：读每个文件一次（同时算 sha256）→ 写进 zip → 直接出网。

代价：没有中间目录，不能重跑 zip；中断即重来。

## 架构

```
浏览器                      docs-api                     数据根
  │                            │                            │
  ├─ POST /exports/preview ───>│ 扫描文件体积 + qdrant 点数   │
  │<── 预估 6.2GB / 25504 ─────┤                            │
  │                            │                            │
  ├─ GET /exports/stream ─────>│                            │
  │   (?task_id=..&group=..)   ├─ 扫描统计 ─────────────────>│
  │                            ├─ qdrant 生成快照 ──────────>│ (1-3min，无字节)
  │                            ├─ 逐文件读 → 算sha256 → zip ─>│
  │<══ zip 字节流（chunked）═══┤                            │
  ├─ GET /{id}/status（轮询）─>│ 阶段文字                    │
  └─ POST /{id}/cancel ───────>│ 置取消位 → 生产者停         │
```

## 后端

### 文件

| 文件 | 动作 |
|---|---|
| `services/docs-core/src/docs_core/corpus_package.py` | **新建**：导出核心 + 进度回调 + 取消检查 |
| `scripts/kb_corpus_export.py` | **改**：瘦成 CLI 壳，行为保持（命令行照旧） |
| `services/docs-api/export_routes.py` | **新建**：4 个路由 |
| `services/docs-api/main.py` | **改**：挂载路由 |

### 核心函数

```python
def scan_selection(data_root, libs) -> ScanResult         # 文件数/字节/sqlite/快照估算/警告
def iter_package_zip(libs, *, on_stage, on_bytes, is_cancelled) -> Iterator[bytes]
```

`iter_package_zip` 是生成器：产 zip 字节流。内部用生产者线程写 zip（非 seekable 流，zipfile 自动用 data descriptor）→ 队列 → 生成器出队 yield。这样进度与取消都能在写侧检查。

**manifest.json 放 zip 最后一项**（sha256 边读边算，读完才齐）。

### 路由

| 方法 | 路径 | 返回 |
|---|---|---|
| POST | `/api/knowledge/exports/preview` | `{total_bytes, file_count, sqlite_bytes, snapshot_bytes, partial_warning}` |
| GET | `/api/knowledge/exports/stream` | zip 字节流（`application/zip`，chunked，无 Content-Length） |
| GET | `/api/knowledge/exports/{task_id}/status` | `{stage, message, bytes_out}` |
| POST | `/api/knowledge/exports/{task_id}/cancel` | `{status}` |

鉴权克隆 `kb_migration_routes.py` 的 `resolve_admin_session`。

### 任务注册表

进程内 dict（`task_id → {stage, message, bytes_out, cancelled}`）。不落库——导出不需要历史；服务重启即失效，前端按「已中断」处理。

**单飞**：同一时间只允许一个导出（第二个请求返回 409）。

### 阶段

| stage | 内容 | 有字节输出？ |
|---|---|---|
| `scan` | 扫描统计（出预估总量） | 否 |
| `snapshot` | 生成并拉取 qdrant 快照 | 否（1-3 分钟） |
| `stream` | 逐文件打包出网 | 是 |

前两段无字节输出，前端显示「准备中」不定态；进入 `stream` 后进度 = `bytes_out / total_bytes`。

## 前端

| 文件 | 动作 |
|---|---|
| `apps/admin-web/src/components/MultiLibraryManager.vue` | **改**：头部加号后加按钮（克隆加号的 icon-only 形态） |
| `apps/admin-web/src/components/kb-export/ExportPackageModal.vue` | **新建**：四态弹框 |
| `apps/admin-web/src/api/knowledge.ts` | **改**：加接口方法 |

### 弹框四态

```
① 选择   组下拉（默认当前组）→ 库复选（默认全选）→ 预估体积
         未全选时红字：
         ⚠ 同组共用一份 sqlite（FTS/graph 不可拆分）：包内仍含未勾选库
           的索引数据。它们没有源文件，检索可能命中、溯源会 404。
② 进行   a-progress（进入 stream 后 determinate）+ 阶段文字 + 取消
③ 完成   文件已保存 / 已发起下载
④ 异常   原因 + 重试
```

### 下载实现

优先 `showSaveFilePicker()` + `fetch` + `ReadableStream` 逐块写盘：能拿到字节计数做进度、能用 `AbortController` 取消。不支持该 API 的浏览器回退 `<a download>` 原生下载（无弹框内进度）。

### 轮询

克隆 `MigrationTaskDrawer.vue` 的 `setInterval` + 连续失败计数（5 次判失联）。

## 风险与边界

| 项 | 说明 |
|---|---|
| **中断即重来** | 无续传；6GB 下到 95% 断了要重导（业主已知情接受） |
| 单飞 | 与迁移任务互不干扰，但导出自身只有一个 |
| 大库 | 22 库全量包估 40GB+，浏览器下载耗时长；分批导是既定策略 |
| `Content-Length` 缺失 | chunked 传输；进度分母是预估值，末尾 ±几 % 漂移 |

## 验收

**功能验收用小库**（业主定：不必上公路库）：`default`（默认知识库，standards 组，1.03G / 19 册）——分钟级跑完，能验全链路。

1. 导 `standards` 组 `default` → zip 能解开、manifest.json 在包内且 sha256 抽验通过
2. **中途取消** → 服务端立即停、无残留、可立即重导
3. **未全选** → 警告出现且文案准确（standards 组另有 lib-39109792 等库可勾掉验证）
4. preview 预估体积与最终 zip 体积误差 < 5%
5. 进度条：`stream` 阶段按字节单调递增；`scan`/`snapshot` 段显示「准备中」

**真实交付验收**（可选，最后做一次）：`standards` 组 `std-highway`（6.19GB / 25504 文件），与 CLI 产物对账。
（原 `guifan` 组，2026-10-09 业主令换名为 `standards`；同一批库与语料，仅组名变化。）

## 不在本次范围

- 导出历史记录（无落库）
- 按库真裁剪 sqlite（需重建 FTS/graph，另立票）
- 定时/自动导出
