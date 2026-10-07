# 规范知识库：制包-导入通道 施工计划

> **For agentic workers:** REQUIRED SUB-SKILL: 用 subagent-driven-development（推荐）或 executing-plans 逐任务执行。步骤用 `- [ ]` 复选框跟踪。

**Goal:** 把本地 2348 册正式规范按专业建库（公路/水运/水利/市政/建筑/电力/综合，层级为库内文件夹，挂 `standards` 组共用一套 sqlite+qdrant），并建成「语料包 export → 生产 import」一条可复用的跨环境通道。

**Architecture:** 三段式——本地制包场（归位+解析+export）→ 语料包（唯一跨环境交付物：registry 行 + 组 sqlite + documents 树 + qdrant snapshot + manifest）→ 生产 angineer.cn 一次 import（模型对账→落盘→探针）。业务层消费走 docs-api HTTP，不碰文件；离线外部方走 CSV 通道（另案）。

**Tech Stack:** Python 3.11+ / FastAPI（docs-api）/ sqlite（registry.sqlite + 组 sqlite）/ qdrant v1.19（snapshot REST API）/ pytest。

**日期:** 2026-10-07。

---

## 已核实的代码事实（施工前先信这些，别重新考古）

| # | 事实 | 位置 |
|---|---|---|
| F1 | 上传即拷贝源文件进规范目录 `libraries/<lib>/documents/<doc_id>/source/`，`file_path` 存该库内路径的**绝对形式** | `services/docs-api/routes/v1/documents.py:227`（save_source_file）→ `docs_service.py:721-744`（register_document 原样存）；拷贝实现 `docs_file_io.py:20-33` |
| F2 | `source_prep` 已有「file_path 是异机路径→读规范目录兜底」机制（有测试锁契约） | `step01_source_prep/source_prep.py:28-47`；测试 `docs-core/tests/test_source_file_fallback.py` |
| F3 | 库→组→存储位置真相源 = `data/registry.sqlite`，两张表 `library_registry`（含 `collection`、`sqlite_file` 相对 data 根 POSIX 路径）与 `library_groups`；读穿不缓存 | `docs_core/library_registry.py:32,79,85,134` |
| F4 | **`standards` 组已有默认**：collection=`"standards"`，组 sqlite=`knowledge/groups/standards.sqlite`（同组库共用一个 sqlite+一个 collection） | `library_registry.py:45-58 GROUP_DEFAULTS`、`:400-405 resolve_collection`、`:408 resolve_index_db_path` |
| F5 | qdrant 集合按库解析：`resolve_collection(library_id)`，payload 有 `library_id` 索引 | `step06_vectors/qdrant_vector_store.py:57-66,111-127,142` |
| F6 | canonical 表（canonical_documents/pages/blocks/outlines）+ FTS5 在 index 库；nodes/libraries/parse_tasks 在 meta 库 | `step05_sqlite_fts/store/canonical_sql_store.py:193-255,343`；`blocks_sql_store.py:73-78` |
| F7 | 无整库导出路由；按文档产物导出已有（含 index/graph 复制） | `step10_export/export_artifacts.py:113` |
| F8 | file_path 其余读点：`parse_pipeline.py:112`（is_file 检查）、`parse_records_store.py:159-176`（getsize/拆后缀）、kb_migrator `:374-393`（前缀改写） | 同左 |
| F9 | 库清单读穿已修（ce34be6），本地不需要重启即见新库；**生产侧该修复未发版，现行 SOP=建库导完重启 aichat-api** | `docs_service.py:547,590,699` |

## 边界（不在本计划内）

- angineer-core 对外发包（PyPI）与业务层 SDK 接入——依赖发版决策，另立一票。
- 离线/外部 pg 方的 CSV 七表通道——形态已定（三雷按交付说明拆），另立一票。
- 扩盘采购本身是用户在腾讯云控制台的操作，本计划只含检查与卡点。

## 提交纪律

每个任务收尾 commit；**push 必须逐次取得用户明确指令**（AGENTS.md 2026-09-13）。生产操作任务在动手前逐项向用户要确认。

---

## Stage A：file_path 相对化（先于一切入库动作）

动机：绝对路径是语料包通道里唯一需要「环境改写」的字段；改成相对 data 根后 export/import 零改写。存量旧绝对行走 F2 兜底不动也能活，能换算的批量清洗。

### Task A1: paths.py 相对化辅助函数（TDD）

**Files:**
- Modify: `services/docs-core/src/docs_core/paths.py`
- Test: `services/docs-core/tests/test_paths_relative.py`（新建）

- [ ] **Step 1: 写失败测试**

```python
# services/docs-core/tests/test_paths_relative.py
from pathlib import Path
import pytest
from docs_core import paths

def test_to_data_relative_posix_under_root(tmp_path, monkeypatch):
    monkeypatch.setenv("ANGINEER_DATA_ROOT", str(tmp_path))
    p = tmp_path / "knowledge" / "libraries" / "lib-x" / "documents" / "d1" / "source" / "a.pdf"
    got = paths.to_data_relative(p)
    assert "\\" not in got and got.startswith("knowledge/libraries/")

def test_to_data_relative_outside_root_passthrough(tmp_path, monkeypatch):
    monkeypatch.setenv("ANGINEER_DATA_ROOT", str(tmp_path))
    outside = tmp_path.parent / "elsewhere.pdf"
    assert paths.to_data_relative(outside) == str(outside)

def test_resolve_node_file_path_relative_and_legacy(tmp_path, monkeypatch):
    monkeypatch.setenv("ANGINEER_DATA_ROOT", str(tmp_path))
    rel = "knowledge/libraries/lib-x/documents/d1/source/a.pdf"
    assert paths.resolve_node_file_path(rel) == tmp_path / rel
    legacy = str(tmp_path / "abs.pdf")
    assert paths.resolve_node_file_path(legacy) == Path(legacy)   # 绝对路径原样
    legacy_win = "D:\\AI\\AnGIneer\\data\\knowledge\\x.pdf"
    assert paths.resolve_node_file_path(legacy_win) == Path(legacy_win)
    assert paths.resolve_node_file_path("") is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd services/docs-core && python -m pytest tests/test_paths_relative.py -v`
Expected: FAIL（`module 'docs_core.paths' has no attribute 'to_data_relative'`）

- [ ] **Step 3: 实现**

```python
# paths.py 追加（放在 resolve_knowledge_base_dir 附近）
def to_data_relative(path: Path | str) -> str:
    """把 data 根之下的绝对路径收敛为 POSIX 相对路径；库外路径原样返回字符串。"""
    p = Path(path)
    root = resolve_data_root()
    try:
        return p.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(p)

def resolve_node_file_path(value: str | None) -> Path | None:
    """nodes.file_path 统一展开：相对值按 data 根展开；绝对/旧值原样；空返回 None。"""
    if not value:
        return None
    p = Path(value)
    if p.is_absolute() or (len(value) > 2 and value[1] == ":"):
        return p
    return resolve_data_root() / p
```

注：`resolve_data_root()` 目前定义在 `library_registry.py:134`（读 `ANGINEER_DATA_ROOT`）。paths.py 里 import 它，或就地把逻辑提为 paths 的私有函数由 library_registry 反向引用——**选前者，别造第二个解析器**。

- [ ] **Step 4: 跑测试确认通过** → 同 Step 2，Expected: 3 passed
- [ ] **Step 5: commit** `feat(docs-core): nodes.file_path 相对化辅助函数 to_data_relative/resolve_node_file_path`

### Task A2: 写入口改存相对路径

**Files:**
- Modify: `services/docs-core/src/docs_core/docs_service.py:721-744`（register_document）
- Test: `services/docs-core/tests/test_paths_relative.py`（追加）

- [ ] **Step 1: 写失败测试**

```python
def test_register_document_stores_relative(tmp_path, monkeypatch):
    monkeypatch.setenv("ANGINEER_DATA_ROOT", str(tmp_path))
    from docs_core.docs_service import DocsService
    svc = DocsService(base_dir=tmp_path / "knowledge")
    src = tmp_path / "knowledge" / "libraries" / "lib-x" / "documents" / "d1" / "source" / "a.pdf"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"x")
    doc_id = svc.register_document("lib-x", str(src), doc_id="d1")
    node = svc.get_node(doc_id)
    assert node.file_path == "knowledge/libraries/lib-x/documents/d1/source/a.pdf"
```

注：DocsService 构造签名以现码为准（`docs_service.py` 类定义处），若单例耦合重（`get_docs_service()`），测试用直接实例化 + tmp base_dir；跑不通先读 `tests/test_delete_library.py` 的夹具姿势再写。

- [ ] **Step 2: 跑测试确认失败**（断言相等失败，实存绝对路径）
- [ ] **Step 3: 实现**——`docs_service.py:740` 改一行：

```python
            file_path=paths.to_data_relative(source_path),
```

- [ ] **Step 4: 跑该文件全部测试 + 兜底契约回归**

Run: `python -m pytest tests/test_paths_relative.py tests/test_source_file_fallback.py -v`
Expected: 全 passed（F2 兜底测试必须不红——它锁的是异机路径仍可读规范目录）

- [ ] **Step 5: docs-api 侧回归**（锁 parse 路由 file_path 契约的三个既有测试）

Run: `cd services/docs-api && python -m pytest tests/test_parse_route_source_fallback.py -v`
Expected: 全 passed

- [ ] **Step 6: commit** `feat(docs-core): register_document 存相对 data 根路径（绝对旧行走解析兜底）`

### Task A3: 读点接 resolver

**Files:**
- Modify: `services/docs-core/src/docs_core/parse_pipeline.py:112`、`:122/:207`（prepare_source 调用传值不改，只改 112 的存在性检查）
- Modify: `services/docs-core/src/docs_core/step01_source_prep/source_prep.py:42`
- Modify: `services/docs-core/src/docs_core/parse_records_store.py:171-176`
- Test: `services/docs-core/tests/test_paths_relative.py`（追加）

- [ ] **Step 1: 失败测试**——「相对 file_path 的行能被 parse_pipeline 判定存在、_ensure_source_file 拷入规范目录」：

```python
def test_ensure_source_file_accepts_relative(tmp_path, monkeypatch):
    monkeypatch.setenv("ANGINEER_DATA_ROOT", str(tmp_path))
    from docs_core.step01_source_prep.source_prep import _ensure_source_file
    rel = "knowledge/libraries/lib-x/documents/d1/source/a.pdf"
    (tmp_path / rel).parent.mkdir(parents=True)
    (tmp_path / rel).write_bytes(b"x")
    # 目标规范目录与源是同一位置（上传后的常态）：兜底路径命中，返回规范路径
    got = _ensure_source_file("lib-x", "d1", file_path=rel, base_dir=tmp_path / "knowledge")
    assert got and Path(got).read_bytes() == b"x"
```

- [ ] **Step 2: 跑→FAIL**（`Path("knowledge/...").exists()` 相对当前 cwd 为 False，走兜底前分支拿不到）
- [ ] **Step 3: 实现**：`source_prep.py:42` 改为 `source_candidate = paths.resolve_node_file_path(file_path)`；`parse_pipeline.py:112` 改为：

```python
    resolved = paths.resolve_node_file_path(ctx.file_path)
    if resolved is None or not resolved.is_file():
```

（原 113 行的报错文案与分支保持。）`parse_records_store.py` 把 171 行 `path = node.file_path or ""` 改为先展开：

```python
    resolved = paths.resolve_node_file_path(node.file_path)
    path = str(resolved) if resolved else ""
```

- [ ] **Step 4: 跑 Step 1 测试 + F2/F8 相关既有测试**（`test_source_file_fallback.py`、`test_parse_records_meta_backfill.py`）Expected 全绿
- [ ] **Step 5: commit** `fix(docs-core): file_path 读点统一走 resolve_node_file_path（相对/绝对/旧值三态兼容）`

### Task A4: 存量行清洗脚本（可重入、dry-run 默认）

**Files:**
- Create: `scripts/relativize_node_file_paths.py`
- Test: 无独立测试文件——脚本本体薄，核心逻辑就是 A1 的 `to_data_relative`，用 `--dry-run` 输出行数当验收

- [ ] **Step 1: 写脚本**：遍历 `data/knowledge/libraries/*/knowledge_meta.sqlite` 与 `data/knowledge/groups/*.sqlite`，对 `nodes.file_path` 逐行 `UPDATE ... SET file_path=? WHERE id=?`（值 = `to_data_relative` 结果；与旧值相同则跳过）。`--dry-run` 只打印「可换算 N 行 / 库外保留 M 行」。旧前缀 `data\knowledge_base\` 的 2976 行属库外保留，靠 F2 兜底。
- [ ] **Step 2: 本地跑 dry-run 对账**（把 N/M 数字记进本票执行记录）
- [ ] **Step 3: `--apply` 执行 + 抽 3 行 SELECT 原样贴给用户核对**
- [ ] **Step 4: commit** `feat(scripts): 存量 nodes.file_path 相对化清洗脚本`

---

## Stage B：2348 册归位（先清单、后动文件）

### Task B1: 归位规划脚本（代号前缀→库）

**Files:**
- Create: `scripts/kb_std_plan.py`
- Test: `scripts/tests/test_kb_std_plan.py`（新建；scripts 下无测试基建则在 `tests/` 挂 `test_kb_std_plan.py`，import 走 `sys.path.insert(0, "scripts")`）

- [ ] **Step 1: 失败测试**

```python
def test_route_by_prefix():
    assert route("JTG_F60-2009 公路交通安全设施设计细则.pdf").library == "公路"
    assert route("JTS 165-2021 水运工程施工规范.pdf").library == "水运"
    assert route("SL 228-2013 土石坝沥青混凝土面板.pdf").library == "水利"
    assert route("CJJ 2-2008 城市桥梁设计规范.pdf").library == "市政"
    assert route("JGJ 130-2011 建筑施工扣件式钢管脚手架.pdf").library == "建筑"
    assert route("DL_T 5044-2014 电力工程直流电源.pdf").library == "电力"
    assert route("GB 50010-2010 混凝土结构设计规范.pdf").library == "待裁决"
    assert route("随便一份没有代号的.docx").library == "待裁决"

def test_tier_by_prefix():
    assert tier_of_filename("GB 50010-2010 混凝土.pdf").tier == "国家标准"
    assert tier_of_filename("DB33_T 1207-2020 某省地标.pdf").tier == "地方标准"
    assert tier_of_filename("T_CETS 001-2019 某团标.pdf").tier == "团体标准"
    assert tier_of_filename("ISO 9001.pdf").tier == "国际标准"
    assert tier_of_filename("JTG_F60-2009 公路.pdf").tier == "行业标准"
```

- [ ] **Step 2: 跑→FAIL** → **Step 3: 实现**（映射表就是清单；`route` 正则取首部代号，长前缀优先；`DB`+省份码→地方标准；待裁决=GB/GBJ/T 无团体源/无法识别）
- [ ] **Step 4: 跑→PASS**
- [ ] **Step 5: 实跑清单**：`python scripts/kb_std_plan.py --root 资料/正式规范 --out data/scratch/std-plan.csv`。Expected: 总 2348 行、自动归位 ≈1900、待裁决 ≈450（GB 607 为主）。CSV 交用户。
- [ ] **Step 6: commit** `feat(scripts): 规范库归位规划脚本（代号前缀→专业库+层级，dry 清单）`

### Task B2: 用户裁决 + 应用移动（人工卡点）

- [ ] **Step 1: 等用户改 CSV**（待裁决行填 library 列；专业列填「公路/水运/水利/市政/建筑/电力/铁路/综合」之一）
- [ ] **Step 2:** `python scripts/kb_std_plan.py --apply data/scratch/std-plan.csv`——按 `<root>/<专业>/<层级>/<原名>` 移动，不重命名文件本体；移动日志落 `data/scratch/std-move.log`
- [ ] **Step 3: 对账**：各目录文件数合计 = 2348；把分布表贴给用户。不动任何 sqlite（这批还没入库）。

---

## Stage C：本地 10 本试点（链路验通，顺带产出规模外推数据）

### Task C1: standards 组建库 + 传 10 本

前置事实：`standards` 组是默认组（F4），公路/水运等 7 库注册进该组即共用 `knowledge/groups/standards.sqlite` + collection `standards`。

- [ ] **Step 1: 确认组与建库路径**：读 `library_registry.py` 的 `create_library`（或 docs-api 建库路由）如何指定 group；若无「指定组」入口，补 CLI 一行调用（`create_library("lib-std-road", group="standards", ...)`）并贴出注册行 SELECT。
- [ ] **Step 2: 从归位后的目录挑 10 本**：纯文字 GB 3、表格密集（含条文表）4、扫描质量差 3。逐本记录文件名+页数。
- [ ] **Step 3: 上传解析**：走 docs-ui 或 `POST /api/v1/documents/parse`（multipart）；轮询 parse_tasks 至终态，记录每本耗时与状态。
- [ ] **Step 4: 算 s/页**，写进 `data/scratch/pilot-10-readout.md`：总页数×平均 s/页 外推 2348 册全量 DGX 时长，失败率外推。这是全量放量排期依据（用户口径：试点目的=验链路，规模=外推）。

### Task C2: 验收探针（含溯源）

- [ ] **Step 1: 检索探针**：对 10 本各出 1 条含条款号的题，走 `knowledge_search`（或 docs-api retrieve），断言：命中该 doc_id、`items[].text` 带《doc_title》前缀、页码字段 0-based 原样。
- [ ] **Step 2: 溯源探针**：对命中 doc_id 调 `GET .../documents/{doc_id}/pdf`（`routes/v1/documents.py:518`）返回 200 且 Content-Type=pdf。
- [ ] **Step 3: 读数贴给用户**，等确认「链路通」再进 Stage D。

---

## Stage D：语料包 export/import（通道本体）

### Task D1: export 脚本

**Files:**
- Create: `scripts/kb_corpus_export.py`
- Test: `tests/test_kb_corpus_export.py`（manifest 生成部分单测）

包结构（定版，写进 manifest）：

```
<out>/<group>-<date>/
├─ manifest.json          # schema_version=1；embed_model（导出现网 .env EMBEDDING_CONFIGS 的 model 名）；
│                         # page_base=0；libs[]：id/name/group/collection/sqlite_file/documents 计数；文件 sha256 表
├─ registry/rows.json     # data/registry.sqlite 中这些库 + 其组 的 library_registry/library_groups 行原样
├─ sqlite/                # registry 行声明的 sqlite_file（相对 data 根的相对路径原样进包——A 段做完即无改写）
├─ documents/             # libraries/<id>/documents/ 全树（源 PDF + 解析产物）
└─ qdrant/<collection>.snapshot
```

- [ ] **Step 1: 失败测试（manifest）**：给定 2 个假库目录 + 假 registry，断言 manifest.json 的 libs[]、sqlite_file 列表、sha256 表覆盖所有落包文件、`page_base==0`。
- [ ] **Step 2: 跑→FAIL** → **Step 3: 实现**：registry 行 SELECT 用 `library_registry` 现成解析函数；sqlite/documents 用 `shutil.copytree`（sqlite 先 `PRAGMA wal_checkpoint(TRUNCATE)`——WAL 四坑）；snapshot 用 REST：`POST localhost:6333/collections/standards/snapshots`，下载文件。
- [ ] **Step 4: 跑→PASS** → **Step 5: commit** `feat(scripts): 语料包 export（registry 行+sqlite+documents+qdrant snapshot+manifest）`

### Task D2: import 脚本（预检硬闸）

**Files:**
- Create: `scripts/kb_corpus_import.py`
- Test: `tests/test_kb_corpus_import.py`（预检逻辑单测）

预检三闸（任一不过即中止，非零退出）：

1. `manifest.embed_model == 现网 .env EMBEDDING_CONFIGS 首个 model` → 不等时只有传 `--reembed` 才放行（放行则跳过快照恢复，导完调 `scripts/rebuild_vectors.py` 重嵌）；
2. 目标 data 根无同名 library_id/collection 冲突；
3. `schema_version` 与代码支持值匹配。

落盘动作：registry 行 INSERT（`INSERT OR REPLACE`，两表）→ sqlite/documents 按 manifest 相对路径放回 → qdrant `POST /snapshots/<name>/recover`（collection 名与目标环境不同时改 `snapshot upload + recover` 带重命名参数）→ 输出「重启 aichat-api + 探针清单」提示。

- [ ] **Step 1: 失败测试**：embed 模型不等→退出码非 0 且提示 `--reembed`；同名 library 已注册→拒绝。
- [ ] **Step 2-4: TDD 循环实现**
- [ ] **Step 5: commit** `feat(scripts): 语料包 import（embed 对账/冲突/schema 三闸+registry 落行+snapshot 恢复）`

---

## Stage E：生产联动（每步都是对外操作，逐项用户确认）

### Task E1: 磁盘卡点

- [ ] **Step 1: 服务器读数**：`/c/Windows/System32/OpenSSH/ssh.exe root@124.221.238.70 'df -h / && du -sm /home/runner/AnGIneer/data'`。可用 <25G 即停，向用户报扩盘需求（包体估：源 13.5G + 产物 8-11G + snapshot ~2.5G）；**扩盘由用户拍板并操作**。

### Task E2: 传包 + import + 重启

- [ ] **Step 1:** `scp -r` 语料包到服务器 `/home/runner/AnGIneer/data/scratch/`（大文件后台、断点用 rsync）
- [ ] **Step 2: 容器内 dry 预检**：`docker exec angineer-docs-api python /app/scripts/kb_corpus_import.py --package <包路径> --dry-run`（需先把两脚本按「运维脚本白名单机制」放行进镜像：`.dockerignore` + `Dockerfile` COPY 两处同改；不放行就 `docker cp` 并在记录里注明副本随容器重建消失）
- [ ] **Step 3: 用户确认后 `--apply`**；若走了 `--reembed`，重嵌在容器内后台跑（nohup+轮询，百万向量按小时估）
- [ ] **Step 4:** `cd docker && docker compose up -d aichat-api`（读穿修复未发版，必须重建，`docker restart` 语义同 AGENTS.md .env 条款——这里只是让新库清单进进程；用 up -d 保持与部署一致）
- [ ] **Step 5: 注意生产容器内路径前缀是 Linux 路径**——A 段之后 manifest 全相对，此处应零改写；若 import 报 file_path 绝对路径残留（导出的是 A 之前的旧包），**停**，重出包，不在生产手改。

### Task E3: 生产验收 + 回滚预案

- [ ] **Step 1: 逐库探针**（同 C2 的题面打生产 docs-api）：每库检索命中、《doc_title》前缀、`/pdf` 200。
- [ ] **Step 2: 顺带回归**：生产既有库任一跑一条老题，确认组化没有把存量 collection 路由搅乱（F5：按库解析，理论无影响，跑一条当证据）。
- [ ] **Step 3: nightly 无扰动确认**：当晚 nightly 读数正常（评测组库与 standards 组分文件分 collection，互不应见）。
- [ ] **回滚预案（写死，出事前演练一次口头确认）**：`DELETE FROM library_registry WHERE library_id IN (...)` → `docker exec angineer-qdrant` 删 collection → 移走组 sqlite/documents。documents 与源 PDF 在生产可整目录删除（语料真相源在本地包）。

### Task E4: 全量放量

- [ ] **Step 1:** 用户拍板排期（避开 nightly 与业务高峰，参考 C1 外推时长），按库分批（建议顺序：公路→水运→水利→市政→建筑→电力→铁路→综合）；每批走完「解析→export→import→探针」闭环再开下一批——包即断点，中断可逐包续。
- [ ] **Step 2:** 全部完成后跑一次全集分布对账（每库文档数 本地=生产），贴表。

---

## Stage F：收尾

- [ ] **F1**: CHANGELOG 段落 + README 摘要（若随发版上线；版本号报用户确认，AGENTS.md 定版）。
- [ ] **F2**: A 段生产全量生效后，AGENTS.md「数据目录迁移契约」补一行：新布局 file_path 已相对化，旧绝对前缀行走 source_prep 兜底；三件套对相对路径库降为两件套。
- [ ] **F3**: 本计划文件按 docs-cleanup 定式处置（完结后删正文、结论进 CHANGELOG）。

## Self-Review 记录

- 覆盖：file_path 改造（A）✔ 归位（B）✔ 试点（C）✔ 通道（D）✔ 生产（E）✔ 扩展性（包与组机制天然覆盖新知识库，F2 文档收口）✔；业务层 SDK 与 pg 方 CSV 明确列在边界外。
- 无占位符：各步含代码/命令/判据；「以现码为准」的两处（DocsService 构造、create_library 组参数）给了替代取证路径，非 TBD。
- 类型一致性：`to_data_relative/resolve_node_file_path` 全文同名；manifest 键（embed_model/page_base/sqlite_file）D1 定义 D2 消费一致。
