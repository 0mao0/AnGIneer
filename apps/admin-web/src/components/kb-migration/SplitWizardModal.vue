<template>
  <a-modal
    :open="props.open"
    :title="`拆分知识库：${props.library?.name || ''}`"
    :width="860"
    :ok-text="current === 1 ? '开始迁移' : '下一步'"
    :cancel-text="current === 1 ? '上一步' : '取消'"
    :ok-button-props="{ disabled: okDisabled, loading: submitting }"
    :mask-closable="false"
    @update:open="(v: boolean) => emit('update:open', v)"
    @cancel="onCancel"
    @ok="onOk"
  >
    <!-- ① 选文档 -->
    <template v-if="current === 0">
      <p class="wiz-lead">把哪些文档分出去？分出去的文档会进一个新库，本库其余文档不动。</p>
      <p class="wiz-volume">{{ sourceVolumeLine }}</p>
      <a-input v-model:value="docFilter" placeholder="按名称过滤文档" allow-clear class="wiz-filter" />
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
          selectedRowKeys: selectedDocIds,
          preserveSelectedRowKeys: true,
          onChange: onSelectionChange,
          getCheckboxProps: (r: any) => ({ disabled: r.type !== 'document' }),
        }"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'name'">
            <span :style="{ paddingLeft: `${Math.min(record.depth, 4) * 16}px` }">
              <FolderOutlined v-if="record.type === 'folder'" />
              <FileTextOutlined v-else />
              {{ record.title }}
            </span>
          </template>
        </template>
      </a-table>
      <div class="wiz-selected-bar">
        已选 {{ selectedDocIds.length }} 篇
        <template v-if="selectionHint">— {{ selectionHint }}</template>
      </div>
    </template>

    <!-- ② 预览 -->
    <template v-else-if="current === 1">
      <a-spin :spinning="previewing">
        <a-form layout="vertical">
          <a-form-item label="新库名称" required>
            <a-input v-model:value="newName" placeholder="新库名称" />
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
              <td>{{ preview.counts.docs.source_after }} 篇（{{ preview.doc_ids.length }} 篇迁出）</td>
            </tr>
            <tr>
              <td>文档（新库「{{ newName || newNameDefault }}」）</td>
              <td>0 篇</td>
              <td>{{ preview.doc_ids.length }} 篇</td>
            </tr>
            <tr><td>内容块</td><td>—</td><td>{{ preview.counts.chunks.moved }} 块随文档迁移</td></tr>
            <tr><td>检索索引</td><td>—</td><td>{{ preview.counts.vectors.moved }} 个向量点随文档迁移</td></tr>
            <tr><td>文件</td><td>—</td><td>{{ preview.counts.files.doc_dirs }} 个文档目录整体搬移</td></tr>
            <tr>
              <td>图谱</td>
              <td>—</td>
              <td>{{ preview.counts.graph.entities }} 个实体、{{ preview.counts.graph.relations }} 条关系随文档迁移</td>
            </tr>
            <tr v-if="preview.eval_refs.datasets.length">
              <td>题集引用</td>
              <td colspan="2">
                {{ evalRefsLine }}——题集与题目不改动，迁移后请确认题集是否仍指向本库
              </td>
            </tr>
          </tbody>
        </table>
        <a-alert
          class="wiz-pause-note"
          type="info"
          show-icon
          message="开始迁移后：本库暂停入库（上传/删除/重解析），读与问答不受影响；完成前可随时取消，已迁移的文档会自动撤回。"
        />
      </a-spin>
    </template>
  </a-modal>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Modal, message } from 'ant-design-vue'
import { FileTextOutlined, FolderOutlined } from '@ant-design/icons-vue'
import { knowledgeApi, type MigrationPreview } from '@/api/knowledge'
import type { KnowledgeLibraryItem } from '@/stores/library'

const props = defineProps<{
  open: boolean
  library: KnowledgeLibraryItem | null
}>()

const emit = defineEmits<{
  (e: 'update:open', v: boolean): void
  (e: 'submitted', taskId: string): void
}>()

const current = ref(0)
const loadingDocs = ref(false)
const submitting = ref(false)
const previewing = ref(false)

interface NodeRow {
  id: string
  title: string
  type: string
  parent_id: string
  depth: number
}

const treeRows = ref<NodeRow[]>([])
const allDocIds = ref<string[]>([])
const selectedDocIds = ref<string[]>([])
const docFilter = ref('')
const newName = ref('')
const preview = ref<MigrationPreview | null>(null)
// 进向导即生成新库 ID：preview 与 submit 复用同一值（服务端不兜底生成，否则 digest 失配）
const newLibraryId = ref('')
const sourceVolumeText = ref('')

const newNameDefault = computed(() => `${props.library?.name || '新库'}-分册`)

const sourceVolumeLine = computed(() => {
  if (sourceVolumeText.value) return `本库共 ${sourceVolumeText.value}`
  return `本库共 ${allDocIds.value.length} 篇文档`
})

const columns = [
  { title: '名称', key: 'name', dataIndex: 'title' },
]

// 过滤只影响表格显示；树结构与文件夹圈选始终走全量 treeRows
const displayRows = computed(() => {
  const kw = docFilter.value.trim().toLowerCase()
  if (!kw) return treeRows.value
  return treeRows.value.filter(
    (r) => r.type === 'document' && String(r.title || '').toLowerCase().includes(kw),
  )
})

// 「下一步」置灰：已选 0 或已选=全部（全部该用合并）
const okDisabled = computed(() => {
  if (current.value === 0) return selectedDocIds.value.length === 0 || previewing.value
  return !preview.value || !newName.value.trim()
})

const selectionHint = computed(() => {
  if (selectedDocIds.value.length === 0) return '至少选择 1 篇文档'
  if (allDocIds.value.length && selectedDocIds.value.length >= allDocIds.value.length) {
    return '已选全部文档——整库并入别的库请用「合并」，不要用拆分'
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
    selectedDocIds.value = []
    docFilter.value = ''
    preview.value = null
    newName.value = newNameDefault.value
    newLibraryId.value = 'lib-' + crypto.randomUUID().replace(/-/g, '').slice(0, 8)
    void loadDocs()
    void loadVolume()
  },
)

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
    const flat: NodeRow[] = []
    const docIds: string[] = []
    const walk = (parentKey: string, depth: number) => {
      for (const n of byParent.get(parentKey) || []) {
        flat.push({ id: n.id, title: String(n.title || n.name || ''), type: n.type, parent_id: String(n.parent_id || ''), depth })
        if (n.type === 'document') docIds.push(n.id)
        else walk(n.id, depth + 1)
      }
    }
    walk('', 0)
    treeRows.value = flat
    allDocIds.value = docIds
  } catch (e: any) {
    message.error('加载文档列表失败: ' + (e.message || e))
  } finally {
    loadingDocs.value = false
  }
}

async function loadVolume() {
  if (!props.library) return
  try {
    const resp = await knowledgeApi.getLibraryVolumes()
    const v = resp.volumes.find((x) => x.library_id === props.library!.id)
    if (v) sourceVolumeText.value = `${v.docs} 篇 · ${(v.chunks / 10000).toFixed(1)} 万块`
  } catch {
    // 体量提示失败不阻塞向导：回落「本库共 N 篇文档」
  }
}

/** 文档后代（文件夹行圈选用） */
function docDescendants(folderId: string): string[] {
  const out: string[] = []
  const stack = [folderId]
  const byParent = new Map<string, NodeRow[]>()
  for (const r of treeRows.value) {
    const key = r.parent_id || ''
    if (!byParent.has(key)) byParent.set(key, [])
    byParent.get(key)!.push(r)
  }
  while (stack.length) {
    const cur = stack.pop()!
    for (const child of byParent.get(cur) || []) {
      if (child.type === 'document') out.push(child.id)
      else stack.push(child.id)
    }
  }
  return out
}

function customRow(record: NodeRow) {
  return {
    onClick: () => {
      if (record.type !== 'folder') return
      const kids = docDescendants(record.id)
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

function onSelectionChange(keys: (string | number)[]) {
  // 文件夹行 checkbox 已禁用；过滤视图下 onChange 只回本页可见 key，做一次并集保护
  const visibleDocKeys = new Set(displayRows.value.filter((r) => r.type === 'document').map((r) => r.id))
  const kept = selectedDocIds.value.filter((id) => !visibleDocKeys.has(id))
  const next = new Set(kept)
  for (const k of keys) {
    const id = String(k)
    const row = treeRows.value.find((r) => r.id === id)
    if (row && row.type === 'document') next.add(id)
  }
  selectedDocIds.value = [...next]
}

async function makePreview() {
  if (!props.library) return
  previewing.value = true
  preview.value = null
  try {
    preview.value = (await knowledgeApi.previewMigration({
      op: 'split',
      source_library_id: props.library.id,
      new_library_id: newLibraryId.value,
      new_name: newName.value.trim() || newNameDefault.value,
      doc_ids: [...selectedDocIds.value],
    })) as unknown as MigrationPreview
  } catch (e: any) {
    message.error(e.message || '预览失败')
    current.value = 0
  } finally {
    previewing.value = false
  }
}

async function doSubmit() {
  if (!props.library || !preview.value) return
  submitting.value = true
  try {
    const resp = (await knowledgeApi.submitMigration({
      op: 'split',
      source_library_id: props.library.id,
      new_library_id: newLibraryId.value,
      new_name: newName.value.trim() || newNameDefault.value,
      doc_ids: [...selectedDocIds.value],
      preview_digest: preview.value.digest,
    })) as unknown as { task_id: string }
    message.success('迁移任务已提交')
    emit('submitted', resp.task_id)
    emit('update:open', false)
  } catch (e: any) {
    if (String(e.message || '').includes('预览已过期')) {
      message.warning('库内容有变化，预览已过期，已自动重新预览')
      current.value = 1
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
    if (!selectedDocIds.value.length) return
    if (allDocIds.value.length && selectedDocIds.value.length >= allDocIds.value.length) {
      message.warning('已选全部文档——整库并入别的库请用「合并」')
      return
    }
    current.value = 1
    void makePreview()
    return
  }
  // step2「开始迁移」= 二次确认弹层（spec §5.8）
  Modal.confirm({
    title: '确认开始拆分迁移？',
    content: `将把 ${selectedDocIds.value.length} 篇文档迁入新库「${newName.value.trim() || newNameDefault.value}」。迁移期间本库暂停入库；完成前可随时取消，已迁移的会自动撤回。`,
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
.wiz-lead {
  margin-bottom: 4px;
}
.wiz-volume {
  color: var(--text-secondary, rgba(0, 0, 0, 0.65));
  margin-bottom: 8px;
}
.wiz-filter {
  margin-bottom: 8px;
  max-width: 280px;
}
.wiz-selected-bar {
  margin-top: 8px;
  font-weight: 600;
}
.wiz-pause-note {
  margin-top: 12px;
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
