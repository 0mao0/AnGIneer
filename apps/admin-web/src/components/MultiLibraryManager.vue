<template>
  <div class="multi-lib-manager" :class="appClass">
    <!-- 内容宽度与「详情」.stats-content 同款：1100px 居中，不横向铺满 -->
    <div class="ml-content">
    <!-- 第一行：左=组切换下拉（详情标题同款）+刷新+建组加号，右=迁移记录 -->
    <div class="ml-page-header">
      <div class="ml-page-header-left">
        <!-- 组切换下拉（2026-10-09 业主定版：删「全部组」选项，默认选中第一个知识组） -->
        <a-dropdown :trigger="['click']">
          <div class="ml-group-trigger">
            <a-tag v-if="titleDomain" class="ml-domain-tag" :color="titleDomain === '外服' ? 'blue' : 'purple'">
              {{ titleDomain }}
            </a-tag>
            <span class="ml-group-name">{{ titleName }}</span>
            <down-outlined class="ml-group-caret" />
          </div>
          <template #overlay>
            <a-menu :selected-keys="groupFilter ? [groupFilter] : []" @click="onGroupMenuClick">
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
        <a-button :loading="loading" title="刷新（体量列强制重算）" @click="() => load(true)">
          <template #icon><reload-outlined /></template>
        </a-button>
        <a-button title="新建知识库组" @click="openCreateGroup">
          <template #icon><plus-outlined /></template>
        </a-button>
        <a-button title="导出语料包" @click="showExport = true">
          <template #icon><download-outlined /></template>
        </a-button>
      </div>
      <div class="ml-page-header-right">
        <a-button type="link" @click="showHistory = true">迁移记录</a-button>
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
      <!-- 组筛选不在此重复放下拉：标题组切换（本组件头部）与本行共用 groupFilter 状态源，双入口一个语义（2026-10-07 业主定版删冗余） -->
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
                <a-tag color="green">正常</a-tag>
                <a-tag v-if="migratedLibIds.has(record.id)" color="blue" title="该库由迁移任务产生或接收了迁入文档">已迁移</a-tag>
              </template>
            </template>
            <template v-else-if="column.key === 'actions'">
              <!-- 字号/间距克隆「详情」页 .action-btns（13px 链接按钮、2px 间距），勿改回 antd 默认 -->
              <span class="action-btns">
                <a-button type="link" size="small" @click="enterLibrary(record)">查看</a-button>
                <a-button
                  type="link"
                  size="small"
                  title="拆并知识库：拆分部分文档到新库/已有库，或整库并入另一个库（整库并入后本库停用）"
                  :disabled="record.status === 'migrating' || !record.doc_count"
                  @click="openSplitFor(record)"
                >
                  拆并
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
              </span>
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
    <SplitMergeWizardModal v-model:open="showSplit" :library="migrationLib" @submitted="onMigrationSubmitted" />
    <MigrationHistoryModal v-model:open="showHistory" @open-task="(id: string) => (activeTaskId = id)" />
    <MigrationTaskDrawer
      :open="!!activeTaskId"
      :task-id="activeTaskId"
      @close="activeTaskId = ''"
      @settled="onMigrationSettled"
    />

    <!-- 语料包导出（服务端流式打包，不落盘） -->
    <ExportPackageModal v-model:open="showExport" :groups="groups" :default-group="groupFilter || ''" />

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
 * 不搬数据（阶段二 flip 才做物理搬迁，见 plan-kb-split-groups；该计划已完结清理）。
 */
import { computed, inject, onActivated, onMounted, ref, type Ref } from 'vue'
import { Modal, message } from 'ant-design-vue'
import { DownOutlined, DownloadOutlined, PlusOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons-vue'
import { useTheme } from '@angineer/ui-kit'
import { DataTable } from '@angineer/table-ui'
import { isMigrationTerminal, knowledgeApi, type LibraryGroupItem } from '@/api/knowledge'
import { GROUP_LABELS, groupLabel } from './kb-group-label'
import { useLibraryStore, type KnowledgeLibraryItem } from '@/stores/library'
import SplitMergeWizardModal from './kb-migration/SplitMergeWizardModal.vue'
import MigrationHistoryModal from './kb-migration/MigrationHistoryModal.vue'
import MigrationTaskDrawer from './kb-migration/MigrationTaskDrawer.vue'
import ExportPackageModal from './kb-export/ExportPackageModal.vue'
import EntityReviewDrawer from './EntityReviewDrawer.vue'

const { appClass } = useTheme()
const libraryStore = useLibraryStore()

// 头部视图状态（App.vue provide）：「查看」= 切到单库管理并选中该库
const knowledgeView = inject<Ref<'multilib' | 'maintenance' | 'nightly' | 'aichat'> | null>('knowledgeView', null)

const groups = ref<LibraryGroupItem[]>([])
const loading = ref(false)
/** load() 调用序号：并发时只有最后一次能收掉刷新圈（否则先回来的旧调用会让按钮提前停转） */
let loadSeq = 0
const saving = ref(false)
const deleting = ref(false)

/** 展示组名与外服/内测 tab 口径一致：注册组中文显示，未知组直出原名。
 *  映射表已抽到 kb-group-label.ts 共用（导出弹框等别处也要显示组名，避免两处漂移）。 */
function groupName(name: string) {
  return groupLabel(name, groups.value)
}

/** 组下拉 = 内置三组 + 已建自定义组（后端聚合含空组，新建后即时可选） */
const groupOptions = computed(() => {
  const opts = Object.entries(GROUP_LABELS).map(([value, label]) => ({ value, label }))
  const builtin = new Set(opts.map((o) => o.value))
  for (const g of groups.value) {
    if (!builtin.has(g.group_name)) opts.push({ value: g.group_name, label: groupLabel(g.group_name, groups.value) })
  }
  return opts
})

/** 单表扁平化：组内顺序保持后端聚合序，行间带 group_name/known_group 供组列与合并禁用判断 */
const flatLibraries = computed(() =>
  groups.value.flatMap((g) =>
    g.libraries.map((lib) => ({ ...lib, group_name: g.group_name, known_group: g.known_group })),
  ),
)

// 集合名直接显示底层的真实值（库注册表 collection 字段 / qdrant 集合名），不做任何改名翻译。
// 曾有一张 { standards: 'system' } 的显示映射（2026-10-09 定版，当时 standards 还是系统库的集合）：
// 后来底层真改名（guifan→standards、旧 standards→system，注册表/物理文件/qdrant 集合全搬），
// 该映射就成了张冠李戴——把规范库的 standards 标成 system（2026-10-09 业主发现），故删除。

// 筛选栏（克隆详情 tab 筛选条）：库名模糊；组精确筛选走标题组切换下拉（同一 groupFilter 状态源；
// 2026-10-09 业主定版无「全部组」——load() 里默认归位第一个知识组）
const libFilter = ref('')
const groupFilter = ref<string | undefined>(undefined)

const filteredLibraries = computed(() => {
  const kw = libFilter.value.trim().toLowerCase()
  return flatLibraries.value.filter((lib) => {
    if (groupFilter.value && lib.group_name !== groupFilter.value) return false
    if (kw && !`${lib.name || ''} ${lib.id}`.toLowerCase().includes(kw)) return false
    return true
  })
})

// 体量列排序取 volumesById 原始值（非展示字符串）；无体量数据记 -1/空串，升序时沉底
function volSortNum(field: 'chunks' | 'vectors' | 'disk') {
  return (a: FlatLib, b: FlatLib): number => {
    const av = volumesById.value.get(a.id)
    const bv = volumesById.value.get(b.id)
    if (!av || !bv) return (av ? 0 : -1) - (bv ? 0 : -1)
    return field === 'disk' ? av.disk_bytes - bv.disk_bytes : av[field] - bv[field]
  }
}

const columns = [
  { title: '知识库', key: 'name', dataIndex: 'name', flex: true, minWidth: 200 },
  { title: '组', key: 'group', width: 130 },
  { title: '文档数', key: 'doc_count', width: 80, sorter: (a: FlatLib, b: FlatLib) => (a.doc_count || 0) - (b.doc_count || 0) },
  { title: '块', key: 'chunks', width: 70, sorter: volSortNum('chunks') },
  { title: '向量', key: 'vectors', width: 70, sorter: volSortNum('vectors') },
  { title: '磁盘', key: 'disk', width: 70, sorter: volSortNum('disk') },
  {
    title: '更新',
    key: 'updated',
    width: 100,
    sorter: (a: FlatLib, b: FlatLib) => (volumesById.value.get(a.id)?.updated_at || '').localeCompare(volumesById.value.get(b.id)?.updated_at || ''),
  },
  { title: '状态', key: 'status', width: 130 },
  // 横向滚动时钉右侧（antdv 原生 fixed，经 table-ui 透传）；
  // 宽度=五颗 13px 链接按钮实测约 178px + 单元格内边距 16px + 余量 10px（与「详情」168/四颗同口径）
  { title: '操作', key: 'actions', width: 204, fixed: 'right' as const },
]

// ── 体量看板（§5.10：只提示不自动动作；失败整列「—」，缓存由服务端 5 分钟承担）──
const volumesById = ref(new Map<string, { docs: number; chunks: number; vectors: number; disk_bytes: number; updated_at?: string }>())
const volumeThresholds = ref<{ docs: number; vectors: number; disk_bytes: number } | null>(null)

async function loadVolumes(force = false) {
  try {
    const resp = await knowledgeApi.getLibraryVolumes(force)
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
        // 拆分的「已迁移」标给新库/接收方；合并给目标库；回滚给收回文档的原目的库
        if (t.op === 'split' && (p.new_library_id || p.target_library_id)) {
          migrated.add(p.new_library_id || p.target_library_id)
        } else if (t.op === 'merge' && p.target_library_id) {
          migrated.add(p.target_library_id)
        } else if (t.op === 'rollback' && p.original_source_library_id) {
          migrated.add(p.original_source_library_id)
        }
      }
    }
    activeTaskIdByLib.value = byLib
    migratedLibIds.value = migrated
    // 页面刷新/切回时若已有迁移在跑，也要盯到它收尾（否则这次入口没有刷新钩子）
    if (byLib.size && !migrationWatchTaskId) watchMigration(byLib.values().next().value as string)
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

/** 「查看」= 切全局选中库 + 跳到「详情」标签：先弹框讲清去哪、怎么回来（业主 2026-10-07：直接跳太突兀） */
function enterLibrary(record: FlatLib) {
  const target = record.name || record.id
  Modal.confirm({
    title: `进入「${target}」的详情页？`,
    content: '会把左侧知识库切到该库，页面从「总览」切到「详情」（解析进度、体量、存储明细在那里）。看完点顶部「总览」标签即可回来。',
    okText: '进入详情',
    cancelText: '取消',
    onOk: () => {
      libraryStore.setLibrary(record.id)
      if (knowledgeView) knowledgeView.value = 'maintenance'
    },
  })
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
  watchMigration(taskId)
}

/** 迁移收尾自动刷新总览（2026-10-09 业主：拆并完成后不刷新，用户以为没成功）。
 *  入库点只有任务行知道：总览的库清单与体量表在任务跑完那一刻才变，提交时刷的是旧数据。
 *  两条触发合流到 settleMigration：① 抽屉看着它跑到终态（秒级）；② 本页盯着这个任务
 *  （抽屉被提前关掉时兜底，5s 一次）。 */
let migrationWatchTaskId = ''
let migrationWatchTimer: number | null = null

function watchMigration(taskId: string) {
  if (!taskId) return
  migrationWatchTaskId = taskId
  if (migrationWatchTimer !== null) return
  migrationWatchTimer = window.setInterval(() => { void pollMigration() }, 5000)
}

function stopMigrationWatch() {
  if (migrationWatchTimer !== null) {
    window.clearInterval(migrationWatchTimer)
    migrationWatchTimer = null
  }
}

async function pollMigration() {
  if (!migrationWatchTaskId) {
    stopMigrationWatch()
    return
  }
  try {
    const t = await knowledgeApi.getMigration(migrationWatchTaskId)
    if (isMigrationTerminal(t.status)) settleMigration(t.status)
  } catch {
    // 瞬时失败下一轮再试（与抽屉同口径，不在这里判死）
  }
}

/** 收尾处理（幂等：抽屉与轮询都可能先到，先到者生效） */
function settleMigration(status: string) {
  if (!migrationWatchTaskId) return
  migrationWatchTaskId = ''
  stopMigrationWatch()
  message.success(status === 'completed' ? '迁移已完成，列表已刷新' : '迁移任务已结束，列表已刷新')
  // 体量列走服务端 5 分钟缓存，这里强制重算，否则看到的还是迁移前的数字
  void load(true)
}

function onMigrationSettled(status: string) {
  settleMigration(status)
}

/** forceVolumes=true（刷新按钮）时体量列强制重算，绕过服务端 5 分钟缓存（2026-10-09 业主定版）。
 *
 *  **按钮转圈要盖住体量列**：块/向量/磁盘三列的数据源是 /migrations/volumes（要遍历各库目录 +
 *  向 qdrant 逐库计数，强算时更慢）。只等库清单就关 loading，会出现「按钮不转了但三列还是旧数」
 *  ——用户据此判断刷新没生效（2026-10-09 业主）。三路都落了才收圈。 */
async function load(forceVolumes = false) {
  const seq = ++loadSeq          // 并发调用时由最后一次决定何时收圈，避免旧的先回来把圈关掉
  loading.value = true
  try {
    try {
      groups.value = sortGroupsForDisplay(await knowledgeApi.getLibraryGroups())
      // 默认显示第一个知识组（2026-10-09 业主定版，原「全部组」已删）：无选中或选中组已不存在时归位显示序第一个
      if (!groups.value.some((g) => g.group_name === groupFilter.value)) {
        groupFilter.value = groups.value[0]?.group_name || undefined
      }
    } catch (err) {
      message.error(`加载库组失败：${(err as Error).message}`)
    }
    // 两者各自吞错不抛，await 只为收圈时机
    await Promise.all([loadMigrationState(), loadVolumes(forceVolumes)])
  } finally {
    if (seq === loadSeq) loading.value = false
  }
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

// ── 导出语料包（docs/design-kb-export-ui.md）：头部按钮 → 选组/库 → 服务端流式打包下载 ──
const showExport = ref(false)

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

/** 组展示顺序（2026-10-07 业主定版）：外服在前、内测在后；外服内 系统库→规范库→DredgeAI。
 *  未列名的自定义组排本域末尾，域前缀由显示名解析（与 tag 同源，改显示名即自动归位）。 */
const GROUP_DISPLAY_ORDER = ['system', 'standards', 'dredgeai', 'evals']

function sortGroupsForDisplay(items: LibraryGroupItem[]): LibraryGroupItem[] {
  const rank = (name: string) => {
    const { domain } = splitGroupLabel(groupName(name))
    return domain === '外服' ? 0 : domain === '内测' ? 1 : 2
  }
  const idx = (name: string) => {
    const i = GROUP_DISPLAY_ORDER.indexOf(name)
    return i === -1 ? GROUP_DISPLAY_ORDER.length : i
  }
  return [...items].sort((a, b) => rank(a.group_name) - rank(b.group_name) || idx(a.group_name) - idx(b.group_name))
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
  groupFilter.value = String(info.key)
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
/* 操作列按钮组：与「详情」页 .action-btns 逐字同款（13px、2px 间距、padding-inline 4px）——
   两页操作列视觉必须一致（业主 2026-10-07）；antd 默认为 14px + 7px 内边距，勿省这一层 */
.action-btns {
  display: inline-flex;
  align-items: baseline;
  gap: 2px;
  white-space: nowrap;
}
.action-btns :deep(.ant-btn) {
  padding-inline: 4px;
  margin-inline: 0;
  height: auto;
  font-size: 13px;
  line-height: 1.5;
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
