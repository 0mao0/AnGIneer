<template>
  <a-modal
    :open="props.open"
    :title="`拆并知识库：${props.library?.name || ''}`"
    :width="860"
    :ok-text="current === 1 ? (isMergeMode ? '确认合并' : '开始迁移') : '下一步'"
    :cancel-text="current === 1 ? '上一步' : '取消'"
    :ok-button-props="{ disabled: okDisabled, loading: submitting, danger: current === 1 && isMergeMode }"
    :mask-closable="false"
    @update:open="(v: boolean) => emit('update:open', v)"
    @cancel="onCancel"
    @ok="onOk"
  >
    <!-- ① 选操作方式（拆分=选文档；整库合并=全库） -->
    <template v-if="current === 0">
      <!-- 不挂 a-form-item：不要「操作方式」标签行（业主 2026-10-07），按钮组自带说明 -->
      <div class="wiz-mode-bar">
        <a-radio-group v-model:value="mode">
          <a-radio-button value="split">拆分：把一部分文档分出去</a-radio-button>
          <a-radio-button value="merge" :disabled="isDefaultSource || !peerLibraries.length">
            整库合并：整库并入另一个库
          </a-radio-button>
        </a-radio-group>
        <span v-if="isDefaultSource" class="wiz-hint">默认库不能整体合并</span>
        <span v-else-if="!peerLibraries.length" class="wiz-hint">本组没有其它可用库</span>
      </div>

      <template v-if="!isMergeMode">
        <!-- 搜索在前、统计在后，同一行（搜索框打头，同「详情/总览」筛选条）；已选计数钉表格右上角 -->
        <div class="wiz-toolbar">
          <a-input v-model:value="docFilter" placeholder="按名称过滤文档" allow-clear class="wiz-filter">
            <template #prefix><search-outlined style="color: rgba(255, 255, 255, 0.25)" /></template>
          </a-input>
          <span class="wiz-volume">{{ sourceVolumeLine }}</span>
          <!-- 默认不显示：一篇都没选时不占位（业主 2026-10-07） -->
          <span v-if="selectedDocIds.length" class="wiz-selected-bar">
            已选 {{ selectedDocIds.length }} 篇
            <template v-if="selectionHint">— {{ selectionHint }}</template>
          </span>
        </div>
        <a-table
          :data-source="displayRows"
          :columns="columns"
          :loading="loadingDocs"
          :row-key="(r: any) => r.id"
          size="small"
          :pagination="{ pageSize: 200, showSizeChanger: false }"
          :scroll="{ y: '52vh' }"
          :custom-row="customRow"
          :row-selection="{
            selectedRowKeys,
            preserveSelectedRowKeys: true,
            onChange: onSelectionChange,
          }"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'name'">
              <span class="wiz-node" :style="{ paddingLeft: `${Math.min(record.depth, 4) * 16}px` }">
                <!-- 文件夹默认折叠（列表太长的库必须），点三角展开；点名字仍是批量选中该文件夹的文档 -->
                <span
                  v-if="record.type === 'folder' && record.hasChildren"
                  class="wiz-caret"
                  :title="expandedFolders.has(record.id) ? '折叠' : '展开'"
                  @click.stop="toggleFolder(record.id)"
                >
                  <DownOutlined v-if="expandedFolders.has(record.id)" />
                  <RightOutlined v-else />
                </span>
                <span v-else class="wiz-caret wiz-caret--empty" />
                <FolderOutlined v-if="record.type === 'folder'" />
                <FileTextOutlined v-else />
                <span
                  class="wiz-node-title"
                  :title="record.type === 'folder' ? '点击批量选中/取消该文件夹下的文档（展开请点左侧三角）' : ''"
                >
                  {{ record.title }}<template v-if="record.type === 'folder'">（{{ record.docCount ?? 0 }}）</template>
                </span>
              </span>
            </template>
          </template>
        </a-table>
      </template>

      <template v-else>
        <p class="wiz-lead">
          本库 {{ sourceSummary }}将全部并入目标库；完成后本库停用（数据不删，7 天内可回滚）。
        </p>
      </template>
    </template>

    <!-- ② 选目的地 + 预览（合并模式带输入库名强确认） -->
    <template v-else-if="current === 1">
      <a-spin :spinning="previewing">
        <a-form layout="vertical">
          <a-form-item v-if="!isMergeMode" label="迁入到哪里" required>
            <a-radio-group v-model:value="destMode">
              <a-radio-button value="new">新建一个库</a-radio-button>
              <a-radio-button value="existing" :disabled="!peerLibraries.length">并入已有库</a-radio-button>
            </a-radio-group>
            <span v-if="!peerLibraries.length" class="wiz-hint">本组没有其它可用库，只能新建</span>
          </a-form-item>
          <a-form-item v-if="!isMergeMode && destMode === 'new'" label="新库名称" required>
            <a-input v-model:value="newName" placeholder="新库名称" />
          </a-form-item>
          <a-form-item v-else label="并入目标库（同组）" required>
            <a-select
              v-model:value="targetId"
              style="width: 100%"
              :placeholder="isMergeMode ? '选择要并入的库' : '选择要迁入的库'"
              :options="targetOptions"
            />
          </a-form-item>
        </a-form>
        <table class="mig-preview-table" v-if="preview">
          <thead>
            <tr><th>迁移内容</th><th>迁移前</th><th>迁移后</th></tr>
          </thead>
          <tbody>
            <tr>
              <td>文档（{{ props.library?.name }}）</td>
              <td>{{ preview.counts.docs.source_before }} 篇</td>
              <td v-if="isMergeMode">0 篇（本库停用）</td>
              <td v-else>{{ preview.counts.docs.source_after }} 篇（{{ preview.doc_ids.length }} 篇迁出）</td>
            </tr>
            <tr v-if="!isMergeMode && destMode === 'new'">
              <td>文档（新库「{{ newName || newNameDefault }}」）</td>
              <td>0 篇</td>
              <td>{{ preview.doc_ids.length }} 篇</td>
            </tr>
            <tr v-else>
              <td>文档（目标库 {{ targetName }}）</td>
              <td>{{ preview.counts.docs.target_before }} 篇</td>
              <td>{{ preview.counts.docs.target_after }} 篇</td>
            </tr>
            <tr><td>内容块</td><td>—</td><td>{{ preview.counts.chunks.moved }} 块随文档迁移</td></tr>
            <tr><td>检索索引</td><td>—</td><td>{{ preview.counts.vectors.moved }} 个向量点随文档迁移</td></tr>
            <tr><td>文件</td><td>—</td><td>{{ preview.counts.files.doc_dirs }} 个文档目录整体搬移</td></tr>
            <tr>
              <td>图谱</td>
              <td>—</td>
              <td>
                {{ preview.counts.graph.entities }} 个实体、{{ preview.counts.graph.relations }} 条关系随文档迁移<template
                  v-if="isMergeMode">；两库同名实体会自动归并</template>
              </td>
            </tr>
            <tr v-if="preview.eval_refs.datasets.length">
              <td>题集引用</td>
              <td colspan="2">
                {{ evalRefsLine }}——题集与题目不改动，{{ isMergeMode ? '合并' : '迁移' }}后请确认题集指向
              </td>
            </tr>
          </tbody>
        </table>
        <a-alert
          v-if="!isMergeMode"
          class="wiz-pause-note"
          type="info"
          show-icon
          :message="destMode === 'new'
            ? '开始迁移后：本库暂停入库（上传/删除/重解析），读与问答不受影响；完成前可随时取消，已迁移的文档会自动撤回。'
            : '开始迁移后：本库与目标库都暂停入库（上传/删除/重解析），读与问答不受影响；完成前可随时取消，已迁移的文档会自动撤回。'"
        />
        <p v-else class="wiz-merge-warning">
          合并后本库停用；期间目标库暂停入库，读与问答不受影响；7 天内可一键回滚。
        </p>
      </a-spin>
    </template>
  </a-modal>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Modal, message } from 'ant-design-vue'
import {
  DownOutlined,
  FileTextOutlined,
  FolderOutlined,
  RightOutlined,
  SearchOutlined,
} from '@ant-design/icons-vue'
import { knowledgeApi, type LibraryVolume, type MigrationPreview, type MigrationSubmitInput } from '@/api/knowledge'
import { libraryGroupOf, useLibraryStore, type KnowledgeLibraryItem } from '@/stores/library'

const props = defineProps<{
  open: boolean
  library: KnowledgeLibraryItem | null
}>()

const emit = defineEmits<{
  (e: 'update:open', v: boolean): void
  (e: 'submitted', taskId: string): void
}>()

const store = useLibraryStore()

const current = ref(0)
const loadingDocs = ref(false)
const submitting = ref(false)
const previewing = ref(false)
/** 操作方式：split=拆分部分文档（目的地二选一），merge=整库并入另一个库（本库停用） */
const mode = ref<'split' | 'merge'>('split')
/** 拆分的目的地形态：new=新建库，existing=并入已有库 */
const destMode = ref<'new' | 'existing'>('new')
const targetId = ref<string | undefined>(undefined)
const volumes = ref<LibraryVolume[]>([])
// 预览乱序保护：快速切换方式/目的地时只认最后一次响应
let previewSeq = 0

interface NodeRow {
  id: string
  title: string
  type: string
  parent_id: string
  depth: number
  hasChildren: boolean
  /** 文件夹（含伪分组）下的文档篇数，展示为「名称（N）」 */
  docCount?: number
}

const treeRows = ref<NodeRow[]>([])
const allDocIds = ref<string[]>([])
const selectedDocIds = ref<string[]>([])
/** 文件夹 id → 其下全部文档 id（含子孙文件夹），勾选框与批量选中共用 */
const folderDocs = ref<Map<string, string[]>>(new Map())
/** 已展开的文件夹（默认全折叠：库大时列表会很长） */
const expandedFolders = ref<Set<string>>(new Set())
const docFilter = ref('')
const newName = ref('')
const preview = ref<MigrationPreview | null>(null)
// 进向导即生成新库 ID：preview 与 submit 复用同一值（服务端不兜底生成，否则 digest 失配）
const newLibraryId = ref('')
const sourceVolumeText = ref('')

const isMergeMode = computed(() => mode.value === 'merge')
const newNameDefault = computed(() => `${props.library?.name || '新库'}-分册`)
const isDefaultSource = computed(() => props.library?.id === 'default')

/** 体量文案：有看板数据用「N 篇 · X 万块」，否则回落文档数 */
const sourceSummary = computed(
  () => sourceVolumeText.value || `${allDocIds.value.length} 篇文档`,
)
const sourceVolumeLine = computed(() => `本库共 ${sourceSummary.value}`)

/** 同组、非自身、非默认库、未退役/未在迁移的可并库（克隆合并向导口径；默认库只出不进） */
const peerLibraries = computed(() => {
  if (!props.library) return []
  const group = libraryGroupOf(props.library)
  return store.libraries.filter((l) => {
    if (l.id === props.library!.id || l.id === 'default') return false
    if (libraryGroupOf(l) !== group) return false
    const v = volumes.value.find((x) => x.library_id === l.id)
    if (v && v.status !== 'active') return false
    return true
  })
})

const targetOptions = computed(() =>
  peerLibraries.value.map((l) => {
    const v = volumes.value.find((x) => x.library_id === l.id)
    return { value: l.id, label: v ? `${l.name} · ${v.docs} 篇` : l.name }
  }),
)

const targetName = computed(
  () => store.libraries.find((l) => l.id === targetId.value)?.name || targetId.value || '',
)

const columns = [
  { title: '名称', key: 'name', dataIndex: 'title' },
]

function toggleFolder(id: string) {
  const next = new Set(expandedFolders.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expandedFolders.value = next
}

/** 根层散装文档（不属于任何文件夹）的伪分组 id：默认折叠，否则大库一屏几百行 */
const ROOT_DOC_GROUP = '__root_docs__'
const rootDocIds = computed(() =>
  treeRows.value.filter((r) => r.depth === 0 && r.type === 'document').map((r) => r.id),
)

/** 折叠视图：只出根层（文件夹＋未分类分组），展开的节点才带子孙（treeRows 是 DFS 序，父行必在子行之前） */
const visibleRows = computed(() => {
  const expanded = expandedFolders.value
  const rootOpen = expanded.has(ROOT_DOC_GROUP)
  const out: NodeRow[] = []
  let hideBelowDepth = Number.POSITIVE_INFINITY // 折叠分支：depth 大于它即隐藏，回到同层/更浅层解除
  let rootGroupPushed = false
  for (const r of treeRows.value) {
    if (r.depth <= hideBelowDepth) hideBelowDepth = Number.POSITIVE_INFINITY
    if (r.depth > hideBelowDepth) continue
    if (r.depth === 0 && r.type === 'document') {
      if (!rootGroupPushed) {
        rootGroupPushed = true
        out.push({
          id: ROOT_DOC_GROUP,
          title: '未分类文档',
          type: 'folder',
          parent_id: '',
          depth: 0,
          hasChildren: true,
          docCount: rootDocIds.value.length,
        })
      }
      if (rootOpen) out.push(r)
      continue
    }
    out.push(r)
    if (r.type === 'folder' && !expanded.has(r.id)) hideBelowDepth = r.depth
  }
  return out
})

// 过滤只影响表格显示；树结构与文件夹圈选始终走全量 treeRows
// 无关键词=折叠视图（默认折叠）；有关键词=全量文档平铺（搜索要能命中折叠内的文档）
const displayRows = computed(() => {
  const kw = docFilter.value.trim().toLowerCase()
  if (!kw) return visibleRows.value
  return treeRows.value.filter(
    (r) => r.type === 'document' && String(r.title || '').toLowerCase().includes(kw),
  )
})

const allSelected = computed(
  () => !!allDocIds.value.length && selectedDocIds.value.length >= allDocIds.value.length,
)

/** 文件夹（含伪分组）下全部文档；勾选框、批量选中共用 */
function docIdsUnder(folderId: string): string[] {
  if (folderId === ROOT_DOC_GROUP) return [...rootDocIds.value]
  return folderDocs.value.get(folderId) || []
}

/** 勾选框状态是派生的：文件夹/伪分组「其下文档全选」时才勾上（antd 无半选态，部分选中显示为未勾） */
const selectedRowKeys = computed(() => {
  const keys = new Set(selectedDocIds.value)
  for (const [fid, docs] of folderDocs.value) {
    if (docs.length && docs.every((d) => keys.has(d))) keys.add(fid)
  }
  if (rootDocIds.value.length && rootDocIds.value.every((d) => keys.has(d))) keys.add(ROOT_DOC_GROUP)
  return [...keys]
})

// 「下一步」置灰；预览步按操作方式与目的地校验（合并模式的二次确认走提交弹框，无库名输入）
const okDisabled = computed(() => {
  if (current.value === 0) {
    if (previewing.value) return true
    return isMergeMode.value ? !peerLibraries.value.length : selectedDocIds.value.length === 0
  }
  if (!preview.value) return true
  if (isMergeMode.value) return false
  return destMode.value === 'new' ? !newName.value.trim() : !targetId.value
})

const selectionHint = computed(() => {
  if (allSelected.value) {
    return isDefaultSource.value
      ? '已选全部文档——默认库不能整体合并，请至少保留 1 篇'
      : '已选全部文档——整库并入别的库请切到「整库合并」'
  }
  return ''
})

const evalRefsLine = computed(() => {
  const refs = preview.value?.eval_refs
  if (!refs || !refs.datasets.length) return ''
  const titles = refs.datasets.map((d) => d.title).join('、')
  const onMoved = refs.questions_on_moved_docs ?? 0
  return `本库被 ${refs.datasets.length} 个题集引用（${titles}），共 ${refs.question_count} 题，其中 ${onMoved} 题用到将迁出的文档`
})

watch(
  () => props.open,
  (open) => {
    if (!open || !props.library) return
    current.value = 0
    mode.value = 'split'
    selectedDocIds.value = []
    expandedFolders.value = new Set() // 每次进向导回到「文件夹全折叠」
    docFilter.value = ''
    preview.value = null
    destMode.value = 'new'
    targetId.value = undefined
    previewSeq += 1 // 作废上一轮未返回的预览响应
    newName.value = newNameDefault.value
    newLibraryId.value = 'lib-' + crypto.randomUUID().replace(/-/g, '').slice(0, 8)
    void loadDocs()
    void loadVolumes()
    if (store.libraries.length === 0) void store.loadLibraries()
  },
)

// 方式/目的地切换即重出预览（名字改动不影响 digest，无需重预览）
watch([mode, destMode, targetId], () => {
  if (current.value !== 1) return
  preview.value = null
  void makePreview()
})

async function loadDocs() {
  if (!props.library) return
  loadingDocs.value = true
  try {
    const nodes = (await knowledgeApi.getNodes(props.library.id, false)) as unknown as any[]
    const byParent = new Map<string, any[]>()
    for (const n of nodes) {
      const key = String(n.parent_id || '')
      if (!byParent.has(key)) byParent.set(key, [])
      byParent.get(key)!.push(n)
    }
    for (const list of byParent.values()) {
      list.sort((a, b) => (a.type === b.type ? Number(a.sort_order || 0) - Number(b.sort_order || 0) : a.type === 'folder' ? -1 : 1))
    }
    // 文件夹 → 其下全部文档 id（含子孙文件夹），供「名称（N）」与勾选框共用；带记忆避免重复递归
    const underCache = new Map<string, string[]>()
    const docsUnder = (folderId: string): string[] => {
      const cached = underCache.get(folderId)
      if (cached) return cached
      const out: string[] = []
      for (const child of byParent.get(folderId) || []) {
        if (child.type === 'document') out.push(String(child.id))
        else out.push(...docsUnder(String(child.id)))
      }
      underCache.set(folderId, out)
      return out
    }
    const flat: NodeRow[] = []
    const docIds: string[] = []
    const walk = (parentKey: string, depth: number) => {
      for (const n of byParent.get(parentKey) || []) {
        flat.push({
          id: n.id,
          title: String(n.title || n.name || ''),
          type: n.type,
          parent_id: String(n.parent_id || ''),
          depth,
          hasChildren: (byParent.get(String(n.id)) || []).length > 0,
          docCount: n.type === 'folder' ? docsUnder(String(n.id)).length : undefined,
        })
        if (n.type === 'document') docIds.push(n.id)
        else walk(n.id, depth + 1)
      }
    }
    walk('', 0)
    treeRows.value = flat
    allDocIds.value = docIds
    folderDocs.value = underCache
  } catch (e: any) {
    message.error('加载文档列表失败: ' + (e.message || e))
  } finally {
    loadingDocs.value = false
  }
}

async function loadVolumes() {
  if (!props.library) return
  try {
    volumes.value = (await knowledgeApi.getLibraryVolumes()).volumes
    const v = volumes.value.find((x) => x.library_id === props.library!.id)
    if (v) sourceVolumeText.value = `${v.docs} 篇 · ${(v.chunks / 10000).toFixed(1)} 万块`
  } catch {
    // 体量提示失败不阻塞向导：回落「本库共 N 篇文档」，目标库下拉只显库名
  }
}

function customRow(record: NodeRow) {
  return {
    onClick: () => {
      if (record.type !== 'folder') return
      const kids = docIdsUnder(record.id)
      if (!kids.length) return
      const set = new Set(selectedDocIds.value)
      const allIn = kids.every((k) => set.has(k))
      for (const k of kids) {
        if (allIn) set.delete(k)
        else set.add(k)
      }
      selectedDocIds.value = [...set]
    },
  }
}

/** 勾选变化：文件夹（含「未分类」伪分组）的勾选态是派生的，只在「刚勾上/刚取消」时连坐其文档 */
function onSelectionChange(keys: (string | number)[]) {
  const keySet = new Set(keys.map((k) => String(k)))
  const prevKeys = new Set(selectedRowKeys.value.map((k) => String(k))) // 变更前的派生键集（含文件夹键）
  // 可见行中没渲染的（折叠内/搜索外的）保持原选择，做一次并集保护
  const visibleDocKeys = new Set(displayRows.value.filter((r) => r.type === 'document').map((r) => r.id))
  const next = new Set(selectedDocIds.value.filter((id) => !visibleDocKeys.has(id)))
  for (const k of keys) {
    const id = String(k)
    const row = treeRows.value.find((r) => r.id === id)
    if (row && row.type === 'document') next.add(id)
    else if (!prevKeys.has(id)) for (const d of docIdsUnder(id)) next.add(d) // 刚勾上文件夹=勾其下全部
  }
  for (const fid of [...folderDocs.value.keys(), ROOT_DOC_GROUP]) {
    if (!prevKeys.has(fid) || keySet.has(fid)) continue // 之前不是全选、或现在还勾着 → 不动
    for (const d of docIdsUnder(fid)) next.delete(d)    // 刚取消勾选文件夹=连坐取消其下全部
  }
  selectedDocIds.value = [...next]
}

/** 当前选择对应的提交体：合并=整库并入；拆分=目的地二选一（并入已有库时不带 new_* 字段） */
function buildPayload(): MigrationSubmitInput | null {
  if (!props.library) return null
  if (isMergeMode.value) {
    if (!targetId.value) return null
    return { op: 'merge', source_library_id: props.library.id, target_library_id: targetId.value }
  }
  const base = {
    op: 'split' as const,
    source_library_id: props.library.id,
    doc_ids: [...selectedDocIds.value],
  }
  if (destMode.value === 'new') {
    return {
      ...base,
      new_library_id: newLibraryId.value,
      new_name: newName.value.trim() || newNameDefault.value,
    }
  }
  if (!targetId.value) return null
  return { ...base, target_library_id: targetId.value }
}

async function makePreview() {
  const payload = buildPayload()
  if (!payload) {
    preview.value = null
    return
  }
  const seq = ++previewSeq
  previewing.value = true
  preview.value = null
  try {
    const resp = (await knowledgeApi.previewMigration(payload)) as unknown as MigrationPreview
    if (seq !== previewSeq) return
    preview.value = resp
  } catch (e: any) {
    if (seq !== previewSeq) return
    message.error(e.message || '预览失败')
    current.value = 0
  } finally {
    if (seq === previewSeq) previewing.value = false
  }
}

async function doSubmit() {
  const payload = buildPayload()
  if (!props.library || !preview.value || !payload) return
  submitting.value = true
  try {
    const resp = (await knowledgeApi.submitMigration({
      ...payload,
      preview_digest: preview.value.digest,
    })) as unknown as { task_id: string }
    message.success(isMergeMode.value ? '合并任务已提交' : '迁移任务已提交')
    emit('submitted', resp.task_id)
    emit('update:open', false)
  } catch (e: any) {
    if (String(e.message || '').includes('预览已过期')) {
      message.warning('库内容有变化，预览已过期，已自动重新预览')
      await makePreview()
    } else {
      message.error(e.message || '提交失败')
    }
  } finally {
    submitting.value = false
  }
}

function onOk() {
  if (current.value === 0) {
    if (isMergeMode.value) {
      if (!peerLibraries.value.length) return
    } else {
      if (!selectedDocIds.value.length) return
      if (allSelected.value) {
        message.warning(isDefaultSource.value
          ? '已选全部文档——默认库不能整体合并，请至少保留 1 篇'
          : '已选全部文档——整库并入请切到「整库合并」')
        return
      }
    }
    current.value = 1
    void makePreview()
    return
  }
  if (isMergeMode.value) {
    // 合并模式：二次确认弹框（原「输入库名」三行已按业主 2026-10-07 去掉，改为提交前弹框确认）
    Modal.confirm({
      title: '确认整库合并？',
      content: `将把「${props.library?.name || ''}」全部 ${preview.value?.counts?.docs?.source_before ?? ''} 篇文档并入「${targetName.value}」；完成后本库停用（数据不删，7 天内可回滚）。`,
      okText: '确认合并',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: () => doSubmit(),
    })
    return
  }
  // 拆分模式 step2「开始迁移」= 二次确认弹层（spec §5.8）
  Modal.confirm({
    title: '确认开始拆分迁移？',
    content: destMode.value === 'new'
      ? `将把 ${selectedDocIds.value.length} 篇文档迁入新库「${newName.value.trim() || newNameDefault.value}」。迁移期间本库暂停入库；完成前可随时取消，已迁移的会自动撤回。`
      : `将把 ${selectedDocIds.value.length} 篇文档并入已有库「${targetName.value}」。迁移期间本库与目标库暂停入库；完成前可随时取消，已迁移的会自动撤回。`,
    okText: '开始迁移',
    onOk: () => doSubmit(),
  })
}

function onCancel() {
  if (current.value === 1 && !submitting.value) {
    // 预览步的「上一步」：回选文档
    current.value = 0
    return
  }
  emit('update:open', false)
}
</script>

<style scoped>
.wiz-mode-bar {
  margin-bottom: 12px;
}
.wiz-lead {
  margin-bottom: 4px;
}
/* 统计 + 搜索同一行：统计在前，搜索在后 */
.wiz-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}
.wiz-volume {
  color: var(--text-secondary, rgba(0, 0, 0, 0.65));
}
.wiz-filter {
  width: 202px; /* 与「详情/总览」筛选条搜索框同宽 */
  flex: none;
}
.wiz-node {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.wiz-caret {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  flex: none;
  color: var(--text-secondary, rgba(0, 0, 0, 0.45));
  cursor: pointer;
  user-select: none;
}
.wiz-caret--empty {
  cursor: default;
}
.wiz-caret:not(.wiz-caret--empty):hover {
  color: var(--primary-color, #1677ff);
}
.wiz-node-title {
  word-break: break-all;
}
.wiz-hint {
  margin-left: 8px;
  color: var(--text-secondary, rgba(0, 0, 0, 0.45));
}
.wiz-selected-bar {
  margin-left: auto; /* 钉在表格右上角：与表格右缘对齐 */
  font-weight: 600;
}
.wiz-pause-note {
  margin-top: 12px;
}
.wiz-merge-warning {
  color: var(--error-color, #ff4d4f);
  margin: 12px 0 8px;
}
.mig-preview-table {
  width: 100%;
  border-collapse: collapse;
}
.mig-preview-table th,
.mig-preview-table td {
  border: 1px solid var(--border-color, #d9d9d9);
  padding: 6px 10px;
  text-align: left;
}
.mig-preview-table th {
  background: var(--bg-secondary, #fafafa);
}
</style>
