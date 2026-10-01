# 题集卡（Dataset Card）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 评测管理页题目列表工具栏加「题集卡」按钮，弹层展示题集元信息（发布方/测试类型/目的/来源/分布/公开锚点），元数据存 `eval_dataset.meta`（JSON 列）。

**Architecture:** 后端在 evals-core 存储层加 meta 列（ALTER 兜底迁移旧库）并沿 bundle 导入/导出、CRUD 全链透传；前端在 evals-ui 包新增只读弹层组件 `EvalDatasetCardModal`（克隆 `EvalRunCreateModal` 骨架），`EvalQuestionList` 工具栏加按钮；回填脚本按 dataset_id/title 匹配给存量题集写 meta，并进镜像白名单以便生产重跑。

**Tech Stack:** Python 3 / sqlite3（evals-core，unittest 测试）、FastAPI（路由零改动——透传靠存储层白名单）、Vue 3 + ant-design-vue（evals-ui 共享包，admin-web 消费）。

**纪律：**
- spec = `docs/req-dataset-card.md`；leaderboard 只放公开锚点（官方论文数字），自家 run 成绩不入卡。
- 本仓库 commit/push 需用户授权：计划中的 commit 步骤**仅在用户授权后执行**。
- 后端测试跑法：`python -m pytest services/evals-core/tests/test_dataset_meta.py -v`（单文件）/
  `python -m pytest services/evals-core/tests -q`（全量回归）。
- 前端 typecheck：`cd packages/evals-ui && npx vue-tsc --noEmit -p tsconfig.json`；
  `cd apps/admin-web && npx vue-tsc -b`。

**执行状态（2026-10-01）：5 任务全部实施并通过验收；commit 待用户授权。**
验收读数：meta 单测 5 passed、evals-core 全量回归 **172 passed**、admin-web `vue-tsc -b` 零错误、
活服务 API 端到端 10/10 题集 meta 为 dict、FinanceBench 详情/导出全字段正确（锚点 3 条、分布 50×3）。
执行偏差（相对下方计划原文）：
1. 回填 ENTRIES 扩为 **11 条**（本地库实存 10 个题集全部灌卡 + 生产-only 的 v4.1）；本地实测发现
   「拒答 39 题」= `open-ragbench-refusal-v2`、「精筛50题」= 海港工程真题（题面核实）；未命中从报错
   降级为警告（本地/生产题集清单本就不同），仅全部未命中才 exit 2。
2. evals-ui 自身无 vue-tsc 二进制（devDeps 只有 typescript）→ typecheck 用 admin-web 的
   `npx vue-tsc -b` 连带校验包源码；`EvalDatasetCardModal` 的 `dataset` prop 因此改 optional。
3. dev aichat-api 重启实况：kill parallel 组内 python 后 **pnpm --parallel 整树退出且不重生**
   （勘误 09-27「反复复活」记忆），docs-api 孤儿存活；已用 Start-Process 脱管重启 aichat-api
   （重定向 %TEMP% 日志）。**8791 现为脱管实例，用户下次自行拉起 dev 前先杀它防端口冲突。**
4. UI 点击验收未做（本地无前端 dev 服务且无 admin 登录态）——以 typecheck + 克隆现成弹框模式兜底，
   留用户在 admin 页点验。

---

### Task 1: 存储层 meta 列——迁移、存取、脏数据兜底（TDD）

**Files:**
- Test: `services/evals-core/tests/test_dataset_meta.py`（新建）
- Modify: `services/evals-core/src/evals_core/storage/result_store.py`

- [ ] **Step 1: 写失败测试**

新建 `services/evals-core/tests/test_dataset_meta.py`（完整文件）：

```python
"""eval_dataset.meta（题集卡元信息）存取与迁移回归。"""

import sys
import tempfile
import unittest
from pathlib import Path

EVALS_CORE_SRC = Path(__file__).resolve().parents[1] / "src"
if str(EVALS_CORE_SRC) not in sys.path:
    sys.path.insert(0, str(EVALS_CORE_SRC))

from evals_core.dataset import manager
from evals_core.storage import result_store

META = {
    "publisher": "Patronus AI",
    "domain": "金融",
    "purpose": "测 SEC 申报文件开放问答",
    "source_url": "https://github.com/patronus-ai/financebench",
    "distribution": [{"label": "metrics-generated", "count": 50}],
    "leaderboard": [{"label": "GPT-4-Turbo 单库RAG", "score": "50%"}],
}

PAYLOAD = {
    "dataset": {
        "dataset_id": "meta-card-test",
        "title": "meta card test",
        "schema_version": "eval.bundle.v2",
        "version": "1.0",
        "library_id": "default",
        "meta": META,
    },
    "items": [
        {
            "question_id": "mq-1",
            "question": "q",
            "task_type": "definition",
            "intent_level": "L1",
            "library_id": "default",
        },
    ],
}


class DatasetMetaStoreTests(unittest.TestCase):
    """meta 列的存取、更新白名单、脏数据兜底与旧库迁移。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._original_db_path = result_store._DB_PATH
        self._original_local = result_store._LOCAL
        self._original_datasets_dir = manager._DATASETS_DIR
        result_store._DB_PATH = str(Path(self._tmp.name) / "evals.sqlite")
        result_store._LOCAL = None
        manager._DATASETS_DIR = str(Path(self._tmp.name) / "datasets")

    def tearDown(self) -> None:
        local = result_store._get_thread_local()
        conn = getattr(local, "conn", None)
        if conn is not None:
            conn.close()
        result_store._LOCAL = self._original_local
        result_store._DB_PATH = self._original_db_path
        manager._DATASETS_DIR = self._original_datasets_dir
        self._tmp.cleanup()

    def test_update_dataset_writes_and_reads_meta(self) -> None:
        """update_dataset 写 meta 后 get 返回原 dict；title 等其它字段不受影响。"""
        manager.import_bundle(PAYLOAD, source_file="test.json")
        updated = manager.update_dataset("meta-card-test", {"meta": META})
        self.assertEqual(updated["meta"], META)
        self.assertEqual(updated["title"], "meta card test")
        row = manager.get_dataset("meta-card-test")
        self.assertEqual(row["meta"], META)

    def test_dirty_meta_falls_back_to_empty_dict(self) -> None:
        """meta 列为非法 JSON 时读出 {}，接口不炸。"""
        manager.import_bundle(PAYLOAD, source_file="test.json")
        conn = result_store._get_conn()
        conn.execute(
            "UPDATE eval_dataset SET meta = 'not-json' WHERE dataset_id = ?",
            ("meta-card-test",),
        )
        conn.commit()
        row = manager.get_dataset("meta-card-test")
        self.assertEqual(row["meta"], {})

    def test_legacy_db_without_meta_column_migrates(self) -> None:
        """旧库（无 meta 列）经 init_db 自动补列：存量行读出 {}，且可继续写 meta。"""
        result_store.init_db()
        conn = result_store._get_conn()
        conn.executescript("""
            DROP TABLE eval_dataset;
            CREATE TABLE eval_dataset (
                dataset_id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT 'knowledge',
                description TEXT NOT NULL DEFAULT '',
                schema_version TEXT NOT NULL DEFAULT 'eval.bundle.v2',
                version TEXT NOT NULL DEFAULT '1.0',
                library_id TEXT NOT NULL DEFAULT 'default',
                question_count INTEGER NOT NULL DEFAULT 0,
                source_file TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT ''
            );
            INSERT INTO eval_dataset (dataset_id, title) VALUES ('legacy-1', 'legacy');
        """)
        conn.commit()
        conn.close()
        result_store._LOCAL = None  # 强制重连，下次 manager 调用触发 init_db 迁移

        rows = manager.list_datasets()
        legacy = next(r for r in rows if r["dataset_id"] == "legacy-1")
        self.assertEqual(legacy["meta"], {})
        updated = manager.update_dataset("legacy-1", {"meta": {"publisher": "AnGIneer"}})
        self.assertEqual(updated["meta"], {"publisher": "AnGIneer"})


if __name__ == "__main__":
    unittest.main()
```

（import/export round-trip 用例放 Task 2——透传改完才可能过。）

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest services/evals-core/tests/test_dataset_meta.py -v`
Expected: 3 个用例全 FAIL（meta 键不存在 / KeyError / 字段缺失）。

- [ ] **Step 3: 改 result_store.py（五处）**

3a. `CREATE TABLE IF NOT EXISTS eval_dataset`（result_store.py:58-70）在 `source_file` 行后加一列：

```sql
            source_file TEXT NOT NULL DEFAULT '',
            meta TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT '',
```

3b. `init_db()` 末尾（`eval_run ADD COLUMN is_full_run` 的 try 块之后，约 line 139-142 附近）追加：

```python
    try:
        conn.execute("ALTER TABLE eval_dataset ADD COLUMN meta TEXT NOT NULL DEFAULT '{}'")
    except Exception:
        pass
```

3c. 在 `_enrich_dataset_with_tree_info`（line 200）之前加解析兜底函数：

```python
def _parse_dataset_meta(raw: Any) -> Dict[str, Any]:
    """meta 列 JSON 解析；脏数据（非法 JSON/非对象）按空 dict 兜底，接口不炸。"""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except (ValueError, TypeError):
            pass
    return {}
```

3d. `_enrich_dataset_with_tree_info` 首行加（list/get/insert 三个出口统一走这里）：

```python
def _enrich_dataset_with_tree_info(conn: sqlite3.Connection, dataset: Dict[str, Any]) -> Dict[str, Any]:
    """从 tree_node 中读取 folder_id 和 sort_order，附加到 dataset 字典上。"""
    dataset["meta"] = _parse_dataset_meta(dataset.get("meta"))
    node = tree_store.get_node(conn, dataset["dataset_id"])
```

3e. `insert_dataset`（line 212-259）：INSERT 列清单与 VALUES 加 meta；`update_dataset`（line 308-311）白名单加 meta + dict 序列化：

```python
def insert_dataset(data: Dict[str, Any]) -> Dict[str, Any]:
    """插入一条测试集记录，同时在 tree_node 中创建对应节点。"""
    now = datetime.now().isoformat()
    raw_meta = data.get("meta")
    meta_text = raw_meta if isinstance(raw_meta, str) else json.dumps(raw_meta or {}, ensure_ascii=False)
    conn = _get_conn()
    conn.execute(
        """INSERT OR REPLACE INTO eval_dataset
           (dataset_id, title, category, description, schema_version, version,
            library_id, question_count, source_file, meta, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            data["dataset_id"],
            data.get("title", ""),
            data.get("category", "knowledge"),
            data.get("description", ""),
            data.get("schema_version", "eval.bundle.v2"),
            data.get("version", "1.0"),
            data.get("library_id", "default"),
            data.get("question_count", 0),
            data.get("source_file", ""),
            meta_text,
            now,
            now,
        ),
    )
```

（tree_node extra 不存 meta——树节点只服务左侧树展示，YAGNI。）

```python
def update_dataset(dataset_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """更新测试集元信息，同步更新 tree_node 中的节点。"""
    allowed = {"title", "description", "category", "meta"}
    normalized = dict(updates)
    if "meta" in normalized and not isinstance(normalized["meta"], str):
        normalized["meta"] = json.dumps(normalized["meta"] or {}, ensure_ascii=False)
    fields = [k for k in normalized if k in allowed and normalized[k] is not None]
    if fields:
        conn = _get_conn()
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = [normalized[k] for k in fields] + [dataset_id]
        conn.execute(f"UPDATE eval_dataset SET {set_clause} WHERE dataset_id = ?", values)
        conn.commit()
```

（`update_dataset` 后半段 tree_node 同步逻辑不动。）

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest services/evals-core/tests/test_dataset_meta.py -v`
Expected: 3 passed。

- [ ] **Step 5: 全量回归**

Run: `python -m pytest services/evals-core/tests -q`
Expected: 无新增失败（存量 23 个测试文件全绿或维持基线）。

- [ ] **Step 6: Commit（待用户授权）**

```bash
git add services/evals-core/src/evals_core/storage/result_store.py services/evals-core/tests/test_dataset_meta.py
git commit -m "feat(evals-core): eval_dataset 加 meta JSON 列（题集卡元信息）——ALTER 兜底迁移旧库、脏数据解析兜底空 dict、update 白名单放行 meta 并序列化"
```

---

### Task 2: schema + manager 透传（bundle 导入/导出携带 meta）

**Files:**
- Modify: `services/evals-core/src/evals_core/dataset/schema.py`
- Modify: `services/evals-core/src/evals_core/dataset/manager.py`
- Test: `services/evals-core/tests/test_dataset_meta.py`（追加用例）

- [ ] **Step 1: 写失败测试（追加到 test_dataset_meta.py 的 `DatasetMetaStoreTests` 类内）**

```python
    def test_import_export_round_trips_meta(self) -> None:
        """bundle 带 meta 导入 → get/export 原样保留。"""
        payload = {
            "dataset": {**PAYLOAD["dataset"]},
            "items": [dict(item) for item in PAYLOAD["items"]],
        }
        manager.import_bundle(payload, source_file="roundtrip.json")
        row = manager.get_dataset("meta-card-test")
        self.assertEqual(row["meta"], META)
        exported = manager.export_dataset("meta-card-test")
        self.assertEqual(exported["dataset"]["meta"], META)

    def test_import_without_meta_defaults_empty(self) -> None:
        """不带 meta 的 bundle 导入后 meta 为 {}（旧题集兼容）。"""
        payload = {
            "dataset": {
                "dataset_id": "no-meta-test",
                "title": "no meta test",
                "schema_version": "eval.bundle.v2",
                "version": "1.0",
                "library_id": "default",
            },
            "items": [dict(item) for item in PAYLOAD["items"]],
        }
        manager.import_bundle(payload, source_file="nometa.json")
        row = manager.get_dataset("no-meta-test")
        self.assertEqual(row["meta"], {})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest services/evals-core/tests/test_dataset_meta.py -v`
Expected: 新增 2 个用例 FAIL（meta 丢失：round-trip 得 `{}`；export 无 meta 键）。Task 1 的 3 个用例保持 passed。

- [ ] **Step 3: 改 schema.py 与 manager.py**

`schema.py` 的 `EvalDatasetMeta`（line ~78）与 `EvalDatasetRow`（line ~88）各加一个字段：

```python
class EvalDatasetMeta(BaseModel):
    """测试集元信息。"""
    dataset_id: str
    title: str
    category: str = "knowledge"
    description: str = ""
    schema_version: str = "eval.bundle.v2"
    version: str = "1.0"
    library_id: str = "default"
    # 题集卡扩展元信息（发布方/测试类型/目的/来源/分布/公开锚点），全可选。
    # 结构见 docs/req-dataset-card.md §2.1；loader 的 model_validate/model_dump 自动透传。
    meta: Dict[str, Any] = Field(default_factory=dict)
```

```python
class EvalDatasetRow(BaseModel):
    """数据库 eval_dataset 行映射。"""
    dataset_id: str
    title: str
    category: str = "knowledge"
    description: str = ""
    schema_version: str = "eval.bundle.v2"
    version: str = "1.0"
    library_id: str = "default"
    meta: Dict[str, Any] = Field(default_factory=dict)
    question_count: int = 0
    source_file: str = ""
    created_at: str = ""
    updated_at: str = ""
```

`manager.py` `import_bundle`（line 32-42）dataset_data 加一行：

```python
    dataset_data = {
        "dataset_id": dataset_meta.dataset_id,
        "title": dataset_meta.title,
        "category": dataset_meta.category,
        "description": dataset_meta.description,
        "schema_version": dataset_meta.schema_version,
        "version": dataset_meta.version,
        "library_id": dataset_meta.library_id,
        "meta": dataset_meta.meta or {},
        "question_count": len(bundle.items),
        "source_file": source_file,
    }
```

`manager.py` `export_dataset`（line 154-163）bundle dataset dict 加一行：

```python
    bundle = EvalBundleV2(
        dataset={
            "dataset_id": dataset["dataset_id"],
            "title": dataset["title"],
            "category": dataset["category"],
            "description": dataset["description"],
            "schema_version": dataset["schema_version"],
            "version": dataset["version"],
            "library_id": dataset["library_id"],
            "meta": dataset.get("meta") or {},
        },
        items=items,
    )
```

（`evals_routes.py` 零改动：GET 直返 row dict、PATCH body 直通 `update_dataset` 白名单、import 走 `load_bundle_from_dict` 校验——meta 全部自动透传。）

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest services/evals-core/tests/test_dataset_meta.py -v`
Expected: 5 passed。

- [ ] **Step 5: 全量回归**

Run: `python -m pytest services/evals-core/tests -q`
Expected: 无新增失败。

- [ ] **Step 6: Commit（待用户授权）**

```bash
git add services/evals-core/src/evals_core/dataset/schema.py services/evals-core/src/evals_core/dataset/manager.py services/evals-core/tests/test_dataset_meta.py
git commit -m "feat(evals-core): 题集卡 meta 沿 bundle 导入/导出与 EvalDatasetMeta/Row 透传——路由层零改动"
```

---

### Task 3: 前端——类型、弹层组件、工具栏按钮、admin 接线

**Files:**
- Modify: `packages/evals-ui/src/types/eval.ts`（`EvalDataset` 接口，line 103-117）
- Create: `packages/evals-ui/src/components/EvalDatasetCardModal.vue`
- Modify: `packages/evals-ui/src/components/EvalQuestionList.vue`（工具栏 line 62-71 之后、props line 111-119、style line 247 附近）
- Modify: `apps/admin-web/src/views/EvalManage.vue`（`<EvalQuestionList>` 调用，line 144-158）

- [ ] **Step 1: types/eval.ts 加类型**

`export interface EvalDataset` 前加，并在 `EvalDataset` 内加字段：

```ts
/** 题集卡扩展元信息（eval_dataset.meta，全可选，由 bundle 导入/回填脚本维护） */
export interface EvalDatasetCardMeta {
  publisher?: string
  domain?: string
  purpose?: string
  source_url?: string
  source_note?: string
  distribution?: { label: string; count: number; note?: string }[]
  leaderboard?: { label: string; score: string; note?: string }[]
}
```

```ts
export interface EvalDataset {
  dataset_id: string
  title: string
  category: EvalDatasetCategory
  description: string
  schema_version: string
  version: string
  library_id: string
  question_count: number
  source_file: string
  meta?: EvalDatasetCardMeta
  folder_id: string
  sort_order: number
  created_at: string
  updated_at: string
}
```

- [ ] **Step 2: 新建 EvalDatasetCardModal.vue（完整文件）**

```vue
<template>
  <a-modal
    :open="open"
    :title="dataset?.title || '题集卡'"
    :footer="null"
    :width="560"
    @cancel="handleCancel"
  >
    <div v-if="dataset" class="eval-dataset-card">
      <a-descriptions :column="1" size="small" bordered>
        <a-descriptions-item label="题数">{{ dataset.question_count }}</a-descriptions-item>
        <a-descriptions-item label="分类">{{ dataset.category }}</a-descriptions-item>
        <a-descriptions-item v-if="card.publisher" label="发布方">{{ card.publisher }}</a-descriptions-item>
        <a-descriptions-item v-if="card.domain" label="测试类型">{{ card.domain }}</a-descriptions-item>
        <a-descriptions-item v-if="card.purpose" label="题集目的">{{ card.purpose }}</a-descriptions-item>
        <a-descriptions-item v-if="card.source_url" label="来源">
          <a :href="card.source_url" target="_blank" rel="noopener">{{ card.source_url }}</a>
          <div v-if="card.source_note" class="eval-dataset-card__note">{{ card.source_note }}</div>
        </a-descriptions-item>
        <a-descriptions-item v-else-if="card.source_note" label="来源说明">{{ card.source_note }}</a-descriptions-item>
      </a-descriptions>

      <template v-if="distributionRows.length">
        <div class="eval-dataset-card__section">题集分布</div>
        <div class="eval-dataset-card__rows">
          <div v-for="row in distributionRows" :key="row.label" class="eval-dataset-card__row">
            <span class="eval-dataset-card__label">{{ row.label }}</span>
            <span class="eval-dataset-card__value">{{ row.count }} 题</span>
            <span v-if="row.note" class="eval-dataset-card__note">{{ row.note }}</span>
          </div>
        </div>
      </template>
      <template v-else-if="levelRows.length">
        <div class="eval-dataset-card__section">层级分布（按题目自动统计）</div>
        <div class="eval-dataset-card__rows">
          <div v-for="row in levelRows" :key="row.label" class="eval-dataset-card__row">
            <span class="eval-dataset-card__label">{{ row.label }}</span>
            <span class="eval-dataset-card__value">{{ row.count }} 题</span>
          </div>
        </div>
      </template>

      <template v-if="leaderboardRows.length">
        <div class="eval-dataset-card__section">公开锚点成绩</div>
        <div class="eval-dataset-card__rows">
          <div v-for="row in leaderboardRows" :key="row.label" class="eval-dataset-card__row">
            <span class="eval-dataset-card__label">{{ row.label }}</span>
            <span class="eval-dataset-card__value">{{ row.score }}</span>
            <span v-if="row.note" class="eval-dataset-card__note">{{ row.note }}</span>
          </div>
        </div>
      </template>

      <a-empty
        v-if="!hasCardMeta"
        description="未登记扩展信息（发布方/来源/锚点等）"
        :image-style="{ height: '48px' }"
      />
    </div>
  </a-modal>
</template>

<script setup lang="ts">
/** 题集卡弹层：只读展示 eval_dataset.meta；meta 缺省退化为题数/分类基础信息。 */
import { computed } from 'vue'
import type { EvalDataset, EvalDatasetCardMeta } from '../types/eval'

const props = defineProps<{
  open: boolean
  dataset: EvalDataset | null
  /** meta.distribution 缺省时按题目层级自动统计 */
  questions?: { intent_level?: string | null }[]
}>()

const emit = defineEmits<{
  'update:open': [open: boolean]
}>()

const card = computed<EvalDatasetCardMeta>(() => props.dataset?.meta || {})

const hasCardMeta = computed(() =>
  Boolean(
    card.value.publisher
    || card.value.domain
    || card.value.purpose
    || card.value.source_url
    || card.value.source_note
    || card.value.distribution?.length
    || card.value.leaderboard?.length
  )
)

const distributionRows = computed(() => card.value.distribution || [])

const levelRows = computed(() => {
  const counts = new Map<string, number>()
  for (const q of props.questions || []) {
    const level = q.intent_level || '未知'
    counts.set(level, (counts.get(level) || 0) + 1)
  }
  return [...counts.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([label, count]) => ({ label, count }))
})

const leaderboardRows = computed(() => card.value.leaderboard || [])

const handleCancel = () => emit('update:open', false)
</script>

<style lang="less" scoped>
.eval-dataset-card {
  display: flex;
  flex-direction: column;
  gap: 12px;

  &__section {
    font-size: 13px;
    font-weight: 600;
  }

  &__rows {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  &__row {
    display: flex;
    align-items: baseline;
    gap: 8px;
    font-size: 12px;
    line-height: 1.6;
  }

  &__label {
    color: var(--text-secondary);
  }

  &__value {
    font-weight: 600;
  }

  &__note {
    color: var(--text-secondary);
    font-size: 11px;
  }
}
</style>
```

- [ ] **Step 3: EvalQuestionList.vue 接按钮与弹层**

3a. 模板：`</a-popover>`（line 71）之后、`</div>`（toolbar 结束）之前加：

```html
      <a-button size="small" class="eval-question-list__card-btn" @click="cardVisible = true">
        题集卡
      </a-button>
```

3b. 模板根元素末尾（`__pagination` div 之后、根 `</div>` 之前）加：

```html
    <EvalDatasetCardModal
      v-model:open="cardVisible"
      :dataset="dataset"
      :questions="questions"
    />
```

3c. script：import 区（`import EvalQuestionCard from './EvalQuestionCard.vue'` 旁）加：

```ts
import EvalDatasetCardModal from './EvalDatasetCardModal.vue'
```

type import（`import type { EvalQuestion, ... } from '../types/eval'`）加 `EvalDataset`：

```ts
import type { EvalQuestion, EvalRunDetail, EvalIntentLevel, EvalQuestionStatus, EvalQuality, EvalDataset } from '../types/eval'
```

props（line 111-119）加 `dataset`：

```ts
const props = defineProps<{
  questions: EvalQuestion[]
  runDetails: Map<string, EvalRunDetail>
  loading: boolean
  evaluatingQuestionIds: Set<string>
  docTreeData?: DocTreeNode[]
  docFlatList?: DocTreeNode[]
  onExpandDetail?: (questionId: string) => void
  dataset?: EvalDataset | null
}>()
```

state 区（`const docTreeVisible = ref(false)` 旁）加：

```ts
const cardVisible = ref(false)
```

3d. style：`.eval-question-list { &__toolbar { ... } ... }` 块内、`&__toolbar` 之后加：

```less
  &__card-btn {
    margin-left: auto;
  }
```

- [ ] **Step 4: admin-web 接线**

`apps/admin-web/src/views/EvalManage.vue` line 144-158 的 `<EvalQuestionList>` 加一个 prop（`:doc-flat-list="docFlatList"` 之后）：

```html
          <EvalQuestionList
            v-if="currentDataset"
            :questions="questions"
            :run-details="runDetails"
            :loading="questionsLoading"
            :evaluating-question-ids="evaluatingQuestionIds"
            :doc-tree-data="docTreeData"
            :doc-flat-list="docFlatList"
            :dataset="currentDataset"
            :on-expand-detail="onQuestionExpandDetail"
            @evaluate="onEvaluateQuestion"
            @update:selected-doc-ids="onSelectedDocIdsChange"
            @question-updated="onQuestionUpdated"
          />
```

（`currentDataset: Ref<EvalDataset | null>` 来自 `packages/evals-ui/src/composables/useEvalDataset.ts:22`，GET /evals/datasets/{id} 响应直灌——后端返回 meta 后自动带上。）

- [ ] **Step 5: typecheck**

Run: `cd packages/evals-ui && npx vue-tsc --noEmit -p tsconfig.json`
Expected: 无错误。
Run: `cd apps/admin-web && npx vue-tsc -b`
Expected: 无错误。

- [ ] **Step 6: Commit（待用户授权）**

```bash
git add packages/evals-ui/src/types/eval.ts packages/evals-ui/src/components/EvalDatasetCardModal.vue packages/evals-ui/src/components/EvalQuestionList.vue apps/admin-web/src/views/EvalManage.vue
git commit -m "feat(evals-ui): 题集卡弹层——工具栏右侧按钮+EvalDatasetCardModal（meta 只读展示、无 meta 退化基础信息+层级自动统计），admin 传入 currentDataset"
```

---

### Task 4: 回填脚本 + 镜像白名单

**Files:**
- Create: `scripts/backfill_dataset_meta.py`
- Modify: `.dockerignore`（line 61 `!scripts/chat_db_gc.py` 之后）
- Modify: `docker/Dockerfile.backend`（line 113 COPY 清单）

- [ ] **Step 1: 新建脚本（完整文件）**

```python
"""题集卡元信息回填：给存量题集写 eval_dataset.meta（默认 dry-run，--apply 才落库）。

匹配规则：dataset_id 精确优先、title 兜底；未命中跳过并在结尾列出。
spec 与 meta 结构见 docs/req-dataset-card.md；生产在容器内重跑同脚本。
"""
import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "evals-core" / "src"))
sys.path.insert(0, str(REPO / "services" / "angineer-core" / "src"))

from evals_core.dataset import manager  # noqa: E402

# FinanceBench 锚点数字 2026-10-01 自官方仓库 /results/ 16 配置原始标注逐文件复算
# （与 arXiv 2311.11944 论文 Table 同源；每配置 150 题人工判）。
ENTRIES = [
    {
        "dataset_id": "financebench-open-150-v1",
        "title": "FinanceBench 开源子集（150 题）",
        "meta": {
            "publisher": "Patronus AI",
            "domain": "金融",
            "purpose": "测 SEC 申报文件（10-K/10-Q/8K/财报）开放问答：数值提取、跨表计算、趋势判断",
            "source_url": "https://github.com/patronus-ai/financebench",
            "source_note": "官方开源子集 150 题全量（metrics/domain/novel 各 50）；语料=84 篇 SEC PDF 回源 EDGAR",
            "distribution": [
                {"label": "metrics-generated", "count": 50},
                {"label": "domain-relevant", "count": 50},
                {"label": "novel-generated", "count": 50},
            ],
            "leaderboard": [
                {
                    "label": "GPT-4-Turbo 单库向量检索（现实 RAG 最优档）",
                    "score": "50%",
                    "note": "150 题人工复核；11% 错 / 39% 拒答",
                },
                {
                    "label": "GPT-4-Turbo Oracle（金证据页直给）",
                    "score": "85%",
                    "note": "非检索配置，不可与 RAG 成绩同表对比",
                },
                {
                    "label": "16 配置人工判汇总",
                    "score": "47%",
                    "note": "arXiv 2311.11944",
                },
            ],
        },
    },
    {
        "dataset_id": "open-ragbench-subset-v4.1",
        "title": "Open RAG Benchmark 子集 v4.1",
        "meta": {
            "publisher": "AnGIneer",
            "domain": "工程（中文规范）",
            "purpose": "端到端 RAG 回归：检索+作答+判分全链路（与 nightly 同源同口径）",
            "source_note": "AnGIneer Open RAG Bench v4.1 子集（金标修订 7 题，2026-09-28 切换）",
        },
    },
    {
        "dataset_id": "clause-probe-v1",
        "title": "条款号直达探针集 v1",
        "meta": {
            "publisher": "AnGIneer",
            "domain": "工程（条款检索）",
            "purpose": "条款号直达：只断言路由层+检索层，不跑生成/判官",
            "source_note": "16 题；题目带 probe_gold 断言块",
        },
    },
    {
        "dataset_id": "intent-router-v1",
        "title": "意图路由测试集 v1",
        "meta": {
            "publisher": "AnGIneer",
            "domain": "意图路由",
            "purpose": "意图分类 L0-L4 路由正确性（不跑检索/生成）",
            "source_note": "100 题；3 次重跑逐题一致",
        },
    },
    {
        "dataset_id": "",
        "title": "拒答 39 题",
        "meta": {
            "publisher": "AnGIneer",
            "domain": "工程",
            "purpose": "超语料负样本：观测拒答守卫行为（预期拒答）",
            "source_note": "39 题；题集 doc_ids 指向库外文档",
        },
    },
]


def _match_row(rows, entry):
    if entry["dataset_id"]:
        for row in rows:
            if row["dataset_id"] == entry["dataset_id"]:
                return row
    for row in rows:
        if row["title"] == entry["title"]:
            return row
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="题集卡元信息回填（dry-run 默认，--apply 落库）")
    parser.add_argument("--apply", action="store_true", help="真正写库")
    args = parser.parse_args()

    rows = manager.list_datasets()
    unmatched = []
    matched = 0
    for entry in ENTRIES:
        row = _match_row(rows, entry)
        if not row:
            unmatched.append(entry["title"])
            continue
        matched += 1
        action = "写库" if args.apply else "将写(dry-run)"
        print(f"[{action}] {row['dataset_id']} ({row['title']}) -> keys: {sorted(entry['meta'])}")
        if args.apply:
            manager.update_dataset(row["dataset_id"], {"meta": entry["meta"]})

    configured = {(e["dataset_id"], e["title"]) for e in ENTRIES}
    leftovers = [
        r for r in rows
        if not any((did and r["dataset_id"] == did) or r["title"] == title for did, title in configured)
    ]
    print(f"命中 {matched}/{len(ENTRIES)}；库内共 {len(rows)} 个题集，未配置 meta 的：")
    for r in leftovers:
        print(f"  - {r['dataset_id']} ({r['title']})")
    if unmatched:
        print(f"ENTRIES 未命中（核对 dataset_id/title）: {unmatched}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: dry-run 核对匹配**

Run: `python scripts/backfill_dataset_meta.py`
Expected: 5 条 `[将写(dry-run)]` 命中（dataset_id 与实际库一致或经 title 兜底命中）、命中 5/5、退出码 0。若FinanceBench 等条目未命中，按打印出的真实 dataset_id 修正 ENTRIES 后重跑。

- [ ] **Step 3: 落库**

Run: `python scripts/backfill_dataset_meta.py --apply`
Expected: 5 条 `[写库]`，退出码 0。

- [ ] **Step 4: GET 验证**

Run: `python -c "import sys; sys.path.insert(0, 'services/evals-core/src'); from evals_core.dataset import manager; [print(r['dataset_id'], '->', r['meta'].get('publisher'), r['meta'].get('domain')) for r in manager.list_datasets() if r['meta']]"`
Expected: 5 行，各带 publisher/domain。

- [ ] **Step 5: 镜像白名单两处同改**

`.dockerignore` line 61 `!scripts/chat_db_gc.py` 后加：

```
!scripts/backfill_dataset_meta.py
```

`docker/Dockerfile.backend` line 113 COPY 清单 `scripts/chat_db_gc.py` 与 `scripts/` 之间加 `scripts/backfill_dataset_meta.py`：

```dockerfile
COPY scripts/migrate_vectors_to_qdrant.py scripts/verify_qdrant_parity.py scripts/build_subset_v3.py scripts/run_omnidocbench_eval.py scripts/fix_node_file_paths.py scripts/repair_inline_math_delims.py scripts/chat_db_gc.py scripts/backfill_dataset_meta.py scripts/
```

- [ ] **Step 6: Commit（待用户授权）**

```bash
git add scripts/backfill_dataset_meta.py .dockerignore docker/Dockerfile.backend
git commit -m "feat(scripts): 题集卡 meta 回填脚本（dry-run 默认）+ 进镜像白名单（.dockerignore 放行与 Dockerfile.backend COPY 两处同改）"
```

---

### Task 5: 端到端验收

- [ ] **Step 1: 重启本地 aichat-api（新代码 + 迁移生效）**

Run: 重启现有 dev 进程（`ANGINEER_NO_RELOAD=1` 已在 .env；杀掉旧进程后 `pnpm dev:aichat-api`）。
Expected: 启动日志无迁移报错。

- [ ] **Step 2: admin 页验收（浏览器）**

- 打开评测管理页 → 选中「FinanceBench 开源子集（150 题）」→ 点工具栏右侧「题集卡」：
  预期完整卡（发布方 Patronus AI / 测试类型 金融 / 目的 / 来源链接 / 分布 3 行各 50 / 锚点 3 行 50%·85%·47%）。
- 切到一个无 meta 的自建题集 → 点「题集卡」：预期基础信息（题数/分类）+ 层级自动统计 +「未登记扩展信息」占位。
- 工具栏按钮位于红框位置（筛选行右侧、不换行遮挡）。

- [ ] **Step 3: 导出再导入 meta 不丢**

Run: `python -c "import sys; sys.path.insert(0, 'services/evals-core/src'); from evals_core.dataset import manager; b = manager.export_dataset('financebench-open-150-v1'); print(b['dataset']['meta']['publisher'], len(b['dataset']['meta']['leaderboard']))"`
Expected: `Patronus AI 3`。

- [ ] **Step 4: 全量回归 + typecheck 终验**

Run: `python -m pytest services/evals-core/tests -q`
Expected: 无新增失败。
Run: `cd apps/admin-web && npx vue-tsc -b`
Expected: 无错误。

- [ ] **Step 5: 生产侧备注（不阻塞本计划完结）**

生产生效需随下个版本部署；部署后在 aichat-api 容器内跑
`python /app/scripts/backfill_dataset_meta.py --apply`（脚本已进镜像白名单）。

---

## Self-Review 记录

- **Spec coverage**：§2.1 数据层→Task 1/2；§2.2 前端→Task 3；§2.3 回填+白名单→Task 4；§3 验收→Task 5；§4 边界（无编辑 UI、自家成绩不入卡）→ENTRIES 无 run 成绩、无编辑组件。无缺口。
- **Placeholder 扫描**：全部步骤含完整代码/命令/预期；无 TBD。
- **类型一致性**：`meta` 字段名全链统一（列名/`EvalDatasetMeta.meta`/`EvalDatasetRow.meta`/API row 键/`EvalDataset.meta`/组件 prop `dataset.meta`）；`_parse_dataset_meta` 仅 Task 1 定义、Task 1 使用；回填 ENTRIES 键与组件渲染字段（publisher/domain/purpose/source_url/source_note/distribution/leaderboard）一一对应。
