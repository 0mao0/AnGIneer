<template>
  <div class="multi-lib-manager" :class="appClass">
    <!-- 内容宽度与「详情」.stats-content 同款：1100px 居中，不横向铺满 -->
    <div class="ml-content">
    <!-- 第一行：左=组切换下拉（详情标题同款）+刷新+建组加号，右=迁移记录 -->
    <div class="ml-page-header">
      <div class="ml-page-header-left">
        <a-dropdown :trigger="['click']">
          <div class="ml-group-trigger">
            <a-tag v-if="titleDomain" class="ml-domain-tag" :color="titleDomain === '外服' ? 'blue' : 'purple'">
              {{ titleDomain }}
            </a-tag>
            <span class="ml-group-name">{{ titleName }}</span>
            <down-outlined class="ml-group-caret" />
          </div>
          <template #overlay>
            <a-menu :selected-keys="[groupFilter || '__all__']" @click="onGroupMenuClick">
              <a-menu-item key="__all__">知识库（全部组）</a-menu-item>
              <a-menu-item v-for="opt in groupMenuOptions" :key="opt.value">
                <span class="ml-menu-group">
                  <a-tag v-if="opt.domain" :color="opt.domain === '外服' ? 'blue' : 'purple'" style="margin: 0">
                    {{ opt.domain }}
                  </a-tag>
                  {{ opt.rest }}
                </span>
              </a-menu-item>
            </a-menu>
          </template>
        </a-dropdown>
        <a-button :loading="loading" title="刷新" @click="load">
          <template #icon><reload-outlined /></template>
        </a-button>
        <a-button title="新建知识库组" @click="openCreateGroup">
          <template #icon><plus-outlined /></template>
        </a-button>
      </div>
      <div class="ml-page-header-right">
        <a-button @click="showHistory = true">
          <template #icon><history-outlined /></template>
          迁移记录
        </a-button>
      </div>
    </div>

    <!-- 第二行：与「详情」页 stats-filter-bar 同款筛选条 -->
    <div class="ml-filter-bar">
      <a-input
        v-model:value="libFilter"
        placeholder="按库名搜索"
        allow-clear
        class="ml-filter-item"
        style="width: 202px"
      >
        <!-- 放大镜颜色照抄「详情」搜索框（KnowledgeStats 内联 rgba .25），两页筛选条同款 -->
        <template #prefix><search-outlined style="color: rgba(255, 255, 255, 0.25)" /></template>
      </a-input>
      <a-select
        v-model:value="groupFilter"
        placeholder="全部组"
        allow-clear
        class="ml-filter-item"
        style="width: 140px"
      >
        <a-select-option v-for="opt in groupFilterOptions" :key="opt.value" :value="opt.value">
          {{ opt.label }}
        </a-select-option>
      </a-select>
      <!-- 新建右对齐，形态克隆「详情」筛选条右端的上传按钮 -->
      <a-button type="primary" style="margin-left: auto" @click="openCreate">
        <template #icon><plus-outlined /></template>
        新建
      </a-button>
    </div>

    <!-- 单表全库一览（spec v2.3：组是列不是分段）；表体克隆「详情」tab 的 DataTable -->
    <DataTable
      :columns="columns"
      :data-source="filteredLibraries"
      :loading="loading"
      row-key="id"
      :card="false"
      :pagination="false"
    >
      <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'name'">
              <div class="ml-lib-name">
                {{ record.name || record.id }}
                <a-tag
                  v-if="isOversize(record.id)"
                  color="orange"
                  class="ml-clickable-tag"
                  title="体量超过拆分建议阈值，点击打开拆分向导"
                  @click="openSplitFor(record)"
                >
                  体量偏大，建议评估拆分
                </a-tag>
              </div>
              <div class="ml-lib-id" :title="record.id">{{ record.id }}{{ record.collection ? ` · ${record.collection}` : '' }}</div>
            </template>
            <template v-else-if="column.key === 'group'">
              <a-tag :color="record.known_group ? 'geekblue' : 'orange'">{{ groupName(record.group_name) }}</a-tag>
              <div v-if="!record.known_group" class="ml-lib-id">未注册组</div>
            </template>
            <template v-else-if="column.key === 'doc_count'">
              <span class="ml-num">{{ record.doc_count }}</span>
            </template>
            <template v-else-if="column.key === 'chunks'">
              <span class="ml-num">{{ volumeCell(record.id, 'chunks') }}</span>
            </template>
            <template v-else-if="column.key === 'vectors'">
              <span class="ml-num">{{ volumeCell(record.id, 'vectors') }}</span>
            </template>
            <template v-else-if="column.key === 'disk'">
              <span class="ml-num">{{ volumeCell(record.id, 'disk') }}</span>
            </template>
            <template v-else-if="column.key === 'updated'">
              <span class="ml-num">{{ volumeCell(record.id, 'updated') }}</span>
            </template>
            <template v-else-if="column.key === 'status'">
              <a-tag v-if="record.status === 'retired'" color="red">已退役</a-tag>
              <a-tag
                v-else-if="record.status === 'migrating'"
                color="gold"
                class="ml-clickable-tag"
                title="查看迁移任务进度"
                @click="openTaskForLib(record.id)"
              >
                迁移中
              </a-tag>
              <template v-else>
                <a-tag>正常</a-tag>
                <a-tag v-if="migratedLibIds.has(record.id)" color="blue" title="该库由迁移任务产生或接收了迁入文档">已迁移</a-tag>
              </template>
            </template>
            <template v-else-if="column.key === 'actions'">
              <a-button type="link" size="small" @click="enterLibrary(record)">查看</a-button>
              <a-button
                type="link"
                size="small"
                title="拆分知识库：把选中的文档拆成新库"
                :disabled="record.id === 'default' || record.status === 'migrating' || !record.doc_count"
                @click="openSplitFor(record)"
              >
                拆分
              </a-button>
              <a-button
                type="link"
                size="small"
                title="合并知识库：把本库并入另一个库"
                :disabled="record.id === 'default' || record.status === 'migrating' || !hasPeerInGroup(record)"
                @click="openMergeFor(record)"
              >
                合并
              </a-button>
              <a-button
                type="link"
                size="small"
                title="实体审核：查看该库图谱实体的待审队列"
                @click="openReviewFor(record)"
              >
                审核
              </a-button>
              <a-button type="link" size="small" @click="openEdit(record)">编辑</a-button>
              <a-button
                type="link"
                size="small"
                danger
                :disabled="record.id === 'default' || record.status === 'migrating'"
                @click="openDelete(record)"
              >
                删除
              </a-button>
            </template>
      </template>
    </DataTable>
    </div><!-- /ml-content -->

    <!-- 新建：名称/描述/所属组 -->
    <a-modal v-model:open="showCreate" title="新建知识库" :confirm-loading="saving" @ok="handleCreate">
      <a-form layout="vertical">
        <a-form-item label="名称" required>
          <a-input v-model:value="createForm.name" placeholder="如：DredgeAI投标知识库" />
        </a-form-item>
        <a-form-item label="描述">
          <a-input v-model:value="createForm.description" placeholder="可选" />
        </a-form-item>
        <a-form-item label="所属组">
          <a-select v-model:value="createForm.group_name" :options="groupOptions" />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- 编辑：default 库禁改名（后端拒），组下拉常驻 -->
    <a-modal v-model:open="showEdit" title="编辑知识库" :confirm-loading="saving" @ok="handleEdit">
      <a-form layout="vertical">
        <a-form-item label="名称" required>
          <a-input v-model:value="editForm.name" :disabled="editForm.id === 'default'" />
        </a-form-item>
        <a-form-item label="描述">
          <a-input v-model:value="editForm.description" placeholder="可选" />
        </a-form-item>
        <a-form-item label="所属组">
          <a-select v-model:value="editForm.group_name" :options="groupOptions" />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- 删除：与 LibrarySelect 同式——输入完整库名确认 -->
    <a-modal
      v-model:open="showDelete"
      title="删除知识库"
      ok-text="永久删除"
      :ok-button-props="{ disabled: deleteInput.trim() !== deleteTarget?.name?.trim() || deleting }"
      @ok="handleDelete"
      @cancel="deleteInput = ''"
    >
      <p class="ml-delete-warning">
        将删除该知识库下的全部节点、文档解析产物、索引与图谱数据，此操作不可恢复。
      </p>
      <p>请输入完整库名确认：</p>
      <p class="ml-delete-name">{{ deleteTarget?.name }}</p>
      <a-input v-model:value="deleteInput" :placeholder="deleteTarget?.name" @pressEnter="handleDelete" />
    </a-modal>

    <!-- 建组（大数据库）：头部加号入口——归入库群二选一，显示名由域前缀拼出 -->
    <a-modal v-model:open="showGroupCreate" title="新建知识库组" ok-text="创建" :confirm-loading="groupCreating" @ok="handleCreateGroup">
      <a-form layout="vertical">
        <a-form-item label="归入库群" required>
          <a-radio-group
            v-model:value="groupCreateForm.domain"
            :options="[
              { label: '外服（生产知识库）', value: 'prod' },
              { label: '内测（评测语料）', value: 'evals' },
            ]"
          />
        </a-form-item>
        <a-form-item label="组名称" required>
          <a-input v-model:value="groupCreateForm.name" placeholder="如：桥梁工程" />
        </a-form-item>
        <a-form-item label="内部标识">
          <a-input v-model:value="groupCreateForm.slug" placeholder="留空自动生成（英文小写/数字/_/-，2–32 位）" />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- 拆分/合并向导 + 迁移记录 + 任务详情（kb-split-merge Task 15-18） -->
    <SplitWizardModal v-model:open="showSplit" :library="migrationLib" @submitted="onMigrationSubmitted" />
    <MergeWizardModal v-model:open="showMerge" :library="migrationLib" @submitted="onMigrationSubmitted" />
    <MigrationHistoryModal v-model:open="showHistory" @open-task="(id: string) => (activeTaskId = id)" />
    <MigrationTaskDrawer :open="!!activeTaskId" :task-id="activeTaskId" @close="activeTaskId = ''" />

    <!-- 实体审核（原 LibrarySelect 下拉图标入口整体迁入，spec v2.3） -->
    <EntityReviewDrawer
      v-model:open="reviewOpen"
      :library-id="reviewLibraryId"
      @changed="loadMigrationState"
      @view-source="onReviewViewSource"
    />
  </div>
</template>

<script setup lang="ts">
/**
 * 总览 tab：全库一览（按组分组）+ 新建 / 改名 / 换组 / 删除。
 * 数据源 GET /knowledge/libraries/groups（后端注册表聚合）；换组只改注册行，
 * 不搬数据（阶段二 flip 才做物理搬迁，见 plan-kb-split-groups）。
 */
import { computed, inject, onActivated, onMounted, ref, type Ref } from 'vue'
import { message } from 'ant-design-vue'
import { DownOutlined, HistoryOutlined, PlusOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons-vue'
import { useTheme } from '@angineer/ui-kit'
import { DataTable } from '@angineer/table-ui'
import { knowledgeApi, type LibraryGroupItem } from '@/api/knowledge'
import { useLibraryStore, type KnowledgeLibraryItem } from '@/stores/library'
import SplitWizardModal from './kb-migration/SplitWizardModal.vue'
import MergeWizardModal from './kb-migration/MergeWizardModal.vue'
import MigrationHistoryModal from './kb-migration/MigrationHistoryModal.vue'
import MigrationTaskDrawer from './kb-migration/MigrationTaskDrawer.vue'
import EntityReviewDrawer from './EntityReviewDrawer.vue'

const { appClass } = useTheme()
const libraryStore = useLibraryStore()

// 头部视图状态（App.vue provide）：「查看」= 切到单库管理并选中该库
const knowledgeView = inject<Ref<'multilib' | 'maintenance' | 'nightly' | 'aichat'> | null>('knowledgeView', null)

const groups = ref<LibraryGroupItem[]>([])
const loading = ref(false)
const saving = ref(false)
const deleting = ref(false)

/** 展示组名与外服/内测 tab 口径一致：注册组中文显示，未知组直出原名 */
const GROUP_LABELS: Record<string, string> = {
  standards: '外服 · 规范标准',
  dredgeai: '外服 · 疏浚工程',
  evals: '内测 · 评测语料',
}

function groupName(name: string) {
  if (GROUP_LABELS[name]) return GROUP_LABELS[name]
  // 自定义组：显示名跟后端 display_name
  return groups.value.find((g) => g.group_name === name)?.display_name || name
}

/** 组下拉 = 内置三组 + 已建自定义组（后端聚合含空组，新建后即时可选） */
const groupOptions = computed(() => {
  const opts = Object.entries(GROUP_LABELS).map(([value, label]) => ({ value, label }))
  const builtin = new Set(opts.map((o) => o.value))
  for (const g of groups.value) {
    if (!builtin.has(g.group_name)) opts.push({ value: g.group_name, label: g.display_name || g.group_name })
  }
  return opts
})

/** 单表扁平化：组内顺序保持后端聚合序，行间带 group_name/known_group 供组列与合并禁用判断 */
const flatLibraries = computed(() =>
  groups.value.flatMap((g) =>
    g.libraries.map((lib) => ({ ...lib, group_name: g.group_name, known_group: g.known_group })),
  ),
)

// 筛选栏（克隆详情 tab 筛选条）：库名模糊 + 组精确；清空 = 全部组（与详情的状态筛选同形态）
const libFilter = ref('')
const groupFilter = ref<string | undefined>(undefined)

const groupFilterOptions = computed(() =>
  groups.value.map((g) => ({ value: g.group_name, label: groupName(g.group_name) })),
)

const filteredLibraries = computed(() => {
  const kw = libFilter.value.trim().toLowerCase()
  return flatLibraries.value.filter((lib) => {
    if (groupFilter.value && lib.group_name !== groupFilter.value) return false
    if (kw && !`${lib.name || ''} ${lib.id}`.toLowerCase().includes(kw)) return false
    return true
  })
})

const columns = [
  { title: '知识库', key: 'name', dataIndex: 'name', flex: true, minWidth: 200 },
  { title: '组', key: 'group', width: 130 },
  { title: '文档数', key: 'doc_count', width: 80 },
  { title: '块', key: 'chunks', width: 70 },
  { title: '向量', key: 'vectors', width: 70 },
  { title: '磁盘', key: 'disk', width: 70 },
  { title: '更新', key: 'updated', width: 100 },
  { title: '状态', key: 'status', width: 130 },
  // 横向滚动时钉右侧（antdv 原生 fixed，经 table-ui 透传）
  { title: '操作', key: 'actions', width: 290, fixed: 'right' as const },
]

// ── 体量看板（§5.10：只提示不自动动作；失败整列「—」，缓存由服务端 5 分钟承担）──
const volumesById = ref(new Map<string, { docs: number; chunks: number; vectors: number; disk_bytes: number; updated_at?: string }>())
const volumeThresholds = ref<{ docs: number; vectors: number; disk_bytes: number } | null>(null)

async function loadVolumes() {
  try {
    const resp = await knowledgeApi.getLibraryVolumes()
    volumesById.value = new Map(resp.volumes.map((v) => [v.library_id, v]))
    volumeThresholds.value = resp.thresholds
  } catch {
    volumesById.value = new Map()
  }
}

function volumeCell(libId: string, field: 'chunks' | 'vectors' | 'disk' | 'updated'): string {
  const v = volumesById.value.get(libId)
  if (!v) return '—'
  if (field === 'chunks') return fmtWan(v.chunks)
  if (field === 'vectors') return fmtWan(v.vectors)
  if (field === 'disk') {
    const gb = v.disk_bytes / 1024 ** 3
    return gb >= 1 ? `${gb.toFixed(1)}G` : `${Math.round(v.disk_bytes / 1024 ** 2)}M`
  }
  return v.updated_at ? String(v.updated_at).slice(0, 10) : '—'
}

function fmtWan(n: number): string {
  return n >= 10000 ? `${(n / 10000).toFixed(1)}万` : String(n)
}

/** 超任一阈值（用响应 thresholds，不硬编码）→ 名称旁软提醒 */
function isOversize(libId: string): boolean {
  const v = volumesById.value.get(libId)
  const t = volumeThresholds.value
  if (!v || !t) return false
  return v.docs > t.docs || v.vectors > t.vectors || v.disk_bytes > t.disk_bytes
}

// ── 迁移入口与任务态（kb-split-merge Task 15）──
const showSplit = ref(false)
const showMerge = ref(false)
const showHistory = ref(false)
const migrationLib = ref<KnowledgeLibraryItem | null>(null)
const activeTaskId = ref('')
/** 库 id → 未完成任务（进行中/中断/失败/取消中，点开可达任务详情） */
const activeTaskIdByLib = ref(new Map<string, string>())
/** 已完成迁移任务涉及的新库/目标库 →「已迁移」角标 */
const migratedLibIds = ref(new Set<string>())

async function loadMigrationState() {
  try {
    const tasks = (await knowledgeApi.listMigrations()).tasks
    const byLib = new Map<string, string>()
    const migrated = new Set<string>()
    for (const t of tasks) {
      const p = t.params || {}
      const libs = [p.source_library_id, p.new_library_id, p.target_library_id,
        p.library_id, p.original_source_library_id].filter(Boolean) as string[]
      if (!['completed', 'cancelled'].includes(t.status)) {
        for (const l of libs) byLib.set(l, t.id)
      }
      if (t.status === 'completed') {
        // 拆分的「已迁移」标给新库；合并给目标库；回滚给收回文档的原目的库
        if (t.op === 'split' && p.new_library_id) migrated.add(p.new_library_id)
        else if (t.op === 'merge' && p.target_library_id) migrated.add(p.target_library_id)
        else if (t.op === 'rollback' && p.original_source_library_id) migrated.add(p.original_source_library_id)
      }
    }
    activeTaskIdByLib.value = byLib
    migratedLibIds.value = migrated
  } catch {
    // 迁移态失败不影响库列表主功能
  }
}

function openTaskForLib(libId: string) {
  const id = activeTaskIdByLib.value.get(libId)
  if (id) activeTaskId.value = id
  else message.info('未找到该库的进行中迁移任务，可在「迁移记录」中查看历史')
}

/** 单表扁平行 = 库行 + 组信息（flatLibraries 直出） */
type FlatLib = LibraryGroupItem['libraries'][number] & { group_name: string; known_group: boolean }

function asMigrationLib(record: FlatLib): KnowledgeLibraryItem {
  return { id: record.id, name: record.name || record.id, group_name: record.group_name }
}

function openSplitFor(record: FlatLib) {
  migrationLib.value = asMigrationLib(record)
  showSplit.value = true
}

function openMergeFor(record: FlatLib) {
  migrationLib.value = asMigrationLib(record)
  showMerge.value = true
}

/** 同组还有第二个可并库（非 default、未退役、不在迁移）才允许合并 */
function hasPeerInGroup(record: FlatLib) {
  const group = groups.value.find((g) => g.group_name === record.group_name)
  if (!group) return false
  return group.libraries.some((l) => {
    if (l.id === record.id || l.id === 'default') return false
    return !l.status || l.status === 'active'
  })
}

function enterLibrary(record: FlatLib) {
  libraryStore.setLibrary(record.id)
  if (knowledgeView) knowledgeView.value = 'maintenance'
}

// ── 实体审核（从 LibrarySelect 下拉迁入）──
const reviewOpen = ref(false)
const reviewLibraryId = ref('default')

function openReviewFor(record: LibraryGroupItem['libraries'][number]) {
  reviewLibraryId.value = record.id
  reviewOpen.value = true
}

/** 「查看原文」在多库页无解析工作台可承接：切到该库的单库管理视图就地定位 */
function onReviewViewSource(payload: { docId: string; libraryId: string }) {
  libraryStore.setLibrary(payload.libraryId || reviewLibraryId.value)
  if (knowledgeView) knowledgeView.value = 'maintenance'
  reviewOpen.value = false
}

function onMigrationSubmitted(taskId: string) {
  activeTaskId.value = taskId
  void loadMigrationState()
  void load()
}

async function load() {
  loading.value = true
  try {
    groups.value = await knowledgeApi.getLibraryGroups()
  } catch (err) {
    message.error(`加载库组失败：${(err as Error).message}`)
  } finally {
    loading.value = false
  }
  void loadMigrationState()
  void loadVolumes()
}

// ── 新建 ──
const showCreate = ref(false)
const createForm = ref({ name: '', description: '', group_name: 'standards' })

function openCreate() {
  createForm.value = { name: '', description: '', group_name: 'standards' }
  showCreate.value = true
}

async function handleCreate() {
  if (!createForm.value.name.trim()) {
    message.warning('请填写名称')
    return
  }
  saving.value = true
  try {
    await knowledgeApi.createLibrary(createForm.value.name.trim(), createForm.value.description, createForm.value.group_name)
    message.success('已创建')
    showCreate.value = false
    await refreshAll()
  } catch (err) {
    message.error(`创建失败：${(err as Error).message}`)
  } finally {
    saving.value = false
  }
}

// ── 编辑（改名 / 改描述 / 换组）──
const showEdit = ref(false)
const editForm = ref({ id: '', name: '', description: '', group_name: 'standards' })

function openEdit(record: FlatLib) {
  editForm.value = {
    id: record.id,
    name: record.name || '',
    description: record.description || '',
    group_name: record.group_name,
  }
  showEdit.value = true
}

async function handleEdit() {
  if (editForm.value.id !== 'default' && !editForm.value.name.trim()) {
    message.warning('请填写名称')
    return
  }
  saving.value = true
  try {
    const patch: { name?: string; description?: string; group_name?: string } = {
      description: editForm.value.description,
    }
    if (editForm.value.id !== 'default') patch.name = editForm.value.name.trim()
    if (editForm.value.group_name) patch.group_name = editForm.value.group_name
    await knowledgeApi.updateLibrary(editForm.value.id, patch)
    message.success('已保存')
    showEdit.value = false
    await refreshAll()
  } catch (err) {
    message.error(`保存失败：${(err as Error).message}`)
  } finally {
    saving.value = false
  }
}

// ── 建组（大数据库）：头部加号弹框，归入外服/内测二选一；显示名 = 域前缀 + 组名，slug 留空自动生成 ──
const showGroupCreate = ref(false)
const groupCreating = ref(false)
const groupCreateForm = ref({ domain: 'prod' as 'prod' | 'evals', name: '', slug: '' })

function openCreateGroup() {
  groupCreateForm.value = { domain: 'prod', name: '', slug: '' }
  showGroupCreate.value = true
}

async function handleCreateGroup() {
  const name = groupCreateForm.value.name.trim()
  if (!name) {
    message.warning('请填写组名称')
    return
  }
  const slug = groupCreateForm.value.slug.trim() || 'grp-' + crypto.randomUUID().replace(/-/g, '').slice(0, 8)
  const display = `${groupCreateForm.value.domain === 'evals' ? '内测' : '外服'} · ${name}`
  groupCreating.value = true
  try {
    await knowledgeApi.createLibraryGroup(slug, display)
    message.success(`组「${display}」已创建`)
    showGroupCreate.value = false
    await load()
    groupFilter.value = slug
  } catch (err) {
    message.error(`建组失败：${(err as Error).message}`)
  } finally {
    groupCreating.value = false
  }
}

// ── 标题组切换（详情标题同款）：菜单选择即按组过滤，与第二行组筛选同一状态源 ──
/** 拆「外服 · 规范标准」= 域 tag + 组名；无域前缀的组不挂 tag */
function splitGroupLabel(label: string): { domain: string; rest: string } {
  const [head, ...rest] = label.split('·')
  const domain = (head || '').trim()
  return domain === '外服' || domain === '内测'
    ? { domain, rest: rest.join('·').trim() || label }
    : { domain: '', rest: label }
}

const groupMenuOptions = computed(() =>
  groups.value.map((g) => ({ value: g.group_name, ...splitGroupLabel(groupName(g.group_name)) })),
)
const titleName = computed(() =>
  groupFilter.value ? splitGroupLabel(groupName(groupFilter.value)).rest : '知识库',
)
const titleDomain = computed(() =>
  groupFilter.value ? splitGroupLabel(groupName(groupFilter.value)).domain : '',
)
function onGroupMenuClick(info: { key: string | number }) {
  groupFilter.value = String(info.key) === '__all__' ? undefined : String(info.key)
}

// ── 删除 ──
const showDelete = ref(false)
const deleteTarget = ref<LibraryGroupItem['libraries'][number] | null>(null)
const deleteInput = ref('')

function openDelete(record: LibraryGroupItem['libraries'][number]) {
  deleteTarget.value = record
  deleteInput.value = ''
  showDelete.value = true
}

async function handleDelete() {
  const target = deleteTarget.value
  if (!target || deleteInput.value.trim() !== target.name.trim()) return
  deleting.value = true
  try {
    await knowledgeApi.deleteLibrary(target.id)
    message.success('已删除')
    showDelete.value = false
    await refreshAll()
  } catch (err) {
    message.error(`删除失败：${(err as Error).message}`)
  } finally {
    deleting.value = false
  }
}

/** 改动后同步刷新本表与全局库 store（详情等其它视图立即看到新库/换组） */
async function refreshAll() {
  await Promise.all([load(), libraryStore.loadLibraries()])
}

onMounted(load)
onActivated(load)
</script>

<style scoped>
.multi-lib-manager {
  height: 100%;
  overflow: auto;
  /* 上 24 与「详情」页外壳同位（实测其 page-header top=80，本容器原 16 会顶到 72） */
  padding: 24px 24px 16px;
}
/* 内容列宽与「详情」.stats-content 逐字同款：1100px 居中（业主定版：不横向铺满） */
.ml-content {
  max-width: 1100px;
  width: 100%;
  margin: 0 auto;
}
/* 第一行：克隆「详情」页 .page-header（左右两段、下边距 16）；
   高 39 = 详情标题实测行高（20px 字 × 1.5714 行高 + 触发器上下 padding 4）——
   两页头部总高锁定一致，表格起始坐标才能逐像素对齐 */
.ml-page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  height: 39px;
  margin-bottom: 16px;
}
.ml-page-header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}
.ml-page-header-left h2 {
  margin: 0;
  color: var(--text-primary);
}
.ml-page-header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}
/* 第二行筛选栏：与「详情」tab 的 .stats-filter-bar 同款（flex-wrap、gap 8、下边距 12） */
.ml-filter-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}
.ml-filter-item {
  min-width: 0;
}
/* 标题组切换：克隆「详情」LibrarySelect title 模式（hover 底色、20px/600 名、12px 箭头） */
.ml-group-trigger {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 4px;
  transition: background-color 0.2s;
}
.ml-group-trigger:hover {
  background-color: var(--bg-secondary, #f5f5f5);
}
.ml-group-name {
  font-size: 20px;
  font-weight: 600;
  color: var(--text-primary);
}
.ml-group-caret {
  font-size: 12px;
  color: var(--text-tertiary);
}
.ml-menu-group {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.ml-lib-name {
  font-weight: 500;
}
.ml-lib-id {
  font-size: 12px;
  color: var(--text-tertiary, rgba(0, 0, 0, 0.45));
  word-break: break-all;
}
.ml-num {
  font-variant-numeric: tabular-nums;
}
.ml-clickable-tag {
  cursor: pointer;
}
.ml-delete-warning {
  color: var(--error-color, #ff4d4f);
  margin-bottom: 12px;
}
.ml-delete-name {
  font-weight: 600;
  word-break: break-all;
  margin-bottom: 8px;
}
</style>
