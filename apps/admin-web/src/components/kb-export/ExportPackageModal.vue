<template>
  <a-modal
    :open="props.open"
    :title="'导出语料包'"
    :width="520"
    :mask-closable="false"
    :closable="state !== 'running'"
    :ok-button-props="{ disabled: state === 'running' || !selectedLibs.length || loadingPreview }"
    :cancel-text="state === 'running' ? '取消导出' : '关闭'"
    :ok-text="state === 'form' ? '开始导出' : state === 'done' ? '再导一次' : '返回'"
    @ok="onOk"
    @cancel="onCancel"
  >
    <!-- ① 选择态：组 + 库勾选 + 体积预估 -->
    <template v-if="state === 'form'">
      <div class="exp-row">
        <span class="exp-label">集合（组）</span>
        <a-select
          v-model:value="groupName"
          :options="groupOptions"
          style="width: 260px"
          @change="onGroupChange"
        />
      </div>

      <div class="exp-row exp-row-top">
        <span class="exp-label">库</span>
        <div class="exp-libs">
          <a-checkbox
            :checked="allChecked"
            :indeterminate="someChecked && !allChecked"
            @change="onToggleAll"
          >
            全选（{{ libsInGroup.length }}）
          </a-checkbox>
          <a-checkbox-group v-model:value="selectedLibs" style="display: block; margin-top: 6px">
            <a-checkbox v-for="lib in libsInGroup" :key="lib.id" :value="lib.id" class="exp-lib-item">
              {{ lib.name }}
              <span class="exp-lib-id">{{ lib.id }}</span>
            </a-checkbox>
          </a-checkbox-group>
        </div>
      </div>

      <a-spin :spinning="loadingPreview">
        <div class="exp-estimate" v-if="preview">
          预计 <b>{{ formatBytes(preview.total_estimate) }}</b>
          （{{ preview.file_count }} 个文件 + 向量快照约 {{ formatBytes(preview.snapshot_estimate) }}）
        </div>
      </a-spin>

      <a-alert
        v-for="(w, i) in previewWarnings"
        :key="i"
        type="warning"
        show-icon
        class="exp-warn"
        :message="w"
      />
      <a-alert
        v-if="preview?.active_task_id"
        type="info"
        show-icon
        class="exp-warn"
        message="当前已有导出任务在运行，需等它结束或取消后再试。"
      />
      <p class="exp-hint">
        包内固定含向量快照与源 PDF（可被对方直接导入检索），不含仅重解析才用得到的中间产物。
      </p>
    </template>

    <!-- ② 进行态：进度条 + 阶段文字 + 取消 -->
    <template v-else-if="state === 'running'">
      <p class="exp-stage">{{ status?.message || '准备中…' }}</p>
      <a-progress
        :percent="status?.percent || 0"
        :status="status?.stage === 'stream' ? 'active' : 'active'"
        size="default"
      />
      <p class="exp-hint">
        <template v-if="status?.stage === 'snapshot'">
          正在生成向量快照，此阶段没有字节输出，约 1-3 分钟。
        </template>
        <template v-else-if="status?.stage === 'stream'">
          已打包 {{ formatBytes(status?.bytes_out || 0) }} / {{ formatBytes(status?.total_bytes || 0) }}
        </template>
        <template v-else>正在统计待打包文件…</template>
      </p>
      <p class="exp-hint exp-hint-dim" v-if="savingMode === 'anchor' && downloadStarted">
        浏览器已开始下载（可在下载栏查看进度）。此处取消会中止服务端导出，浏览器侧留下的是不完整文件，请删除。
      </p>
    </template>

    <!-- ③ 完成态 -->
    <template v-else-if="state === 'done'">
      <a-result status="success" title="导出完成" :sub-title="doneSubTitle" />
      <p class="exp-hint" v-if="savingMode === 'anchor'">文件已保存到浏览器下载目录。</p>
      <p class="exp-hint" v-else>文件已保存到你选择的位置。</p>
    </template>

    <!-- ④ 取消态 -->
    <template v-else-if="state === 'cancelled'">
      <a-result status="warning" title="已取消导出" sub-title="服务端已停止，未保存文件（临时快照已清理）。" />
    </template>

    <!-- ⑤ 异常态 -->
    <template v-else>
      <a-result status="error" title="导出失败" :sub-title="errorMsg" />
    </template>
  </a-modal>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { knowledgeApi, type ExportPreview, type ExportStatus, type LibraryGroupItem } from '@/api/knowledge'
import { useLibraryStore, type KnowledgeLibraryItem } from '@/stores/library'

const props = defineProps<{
  open: boolean
  groups: LibraryGroupItem[]
  /** 打开时默认选中的组（当前页标题组） */
  defaultGroup?: string
}>()
const emit = defineEmits<{ (e: 'update:open', v: boolean): void }>()

const libraryStore = useLibraryStore()

type State = 'form' | 'running' | 'done' | 'cancelled' | 'error'
const state = ref<State>('form')
const groupName = ref<string>('')
const selectedLibs = ref<string[]>([])
const preview = ref<ExportPreview | null>(null)
const loadingPreview = ref(false)
const status = ref<ExportStatus | null>(null)
const errorMsg = ref('')
const savedBytes = ref(0)
/** 保存通道：fsAccess=File System Access API（可精确计数、可弃写）；anchor=浏览器原生下载 */
const savingMode = ref<'fsAccess' | 'anchor'>('anchor')
const downloadStarted = ref(false)

let taskId = ''
let pollTimer: number | null = null
let pollFailCount = 0
let unknownCount = 0

const groupOptions = computed(() =>
  props.groups.map((g) => ({ value: g.group_name, label: g.display_name || g.group_name })),
)

const libsInGroup = computed<KnowledgeLibraryItem[]>(() => {
  const found = props.groups.find((g) => g.group_name === groupName.value)
  if (found) return found.libraries.map((l) => ({ id: l.id, name: l.name, group_name: found.group_name }))
  return (libraryStore.libraries || []).filter((l) => (l.group_name || 'standards') === groupName.value)
})

const allChecked = computed(() => libsInGroup.value.length > 0 && selectedLibs.value.length === libsInGroup.value.length)
const someChecked = computed(() => selectedLibs.value.length > 0)

/** 后端给的权威文案；仅当未选中的同组库确实「可勾选」时才追加「建议全选」
 *  （空库不进可选清单，对它们说「全选」是点不到的建议）。 */
const previewWarnings = computed(() => {
  const p = preview.value
  if (!p) return []
  const out = [...p.warnings]
  const selectable = new Set(p.selectable_library_ids || [])
  const unselectedSelectable = (p.peers || []).filter((peer) => selectable.has(peer.library_id))
  if (unselectedSelectable.length) out.push(`建议全选该组所有库（还有 ${unselectedSelectable.length} 个可选未勾选）。`)
  return out
})

function formatBytes(n: number): string {
  if (!n) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  let v = n
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i += 1
  }
  return `${v >= 100 ? v.toFixed(0) : v.toFixed(2)} ${units[i]}`
}

const doneSubTitle = computed(() => `已导出 ${formatBytes(savedBytes.value || status.value?.total_bytes || 0)}`)

function onToggleAll(e: any) {
  selectedLibs.value = e.target.checked ? libsInGroup.value.map((l) => l.id) : []
}

function onGroupChange() {
  // 换组默认全选（同组共用 sqlite，全选才是自洽形态）
  selectedLibs.value = libsInGroup.value.map((l) => l.id)
  preview.value = null
  void loadPreview()
}

async function loadPreview() {
  if (!selectedLibs.value.length) {
    preview.value = null
    return
  }
  loadingPreview.value = true
  try {
    preview.value = await knowledgeApi.previewExport(selectedLibs.value)
  } catch (e: any) {
    message.error('预估失败：' + (e?.response?.data?.detail || e?.message || e))
  } finally {
    loadingPreview.value = false
  }
}

watch(
  () => props.open,
  (open) => {
    if (!open) {
      stopPolling()
      return
    }
    state.value = 'form'
    status.value = null
    errorMsg.value = ''
    savedBytes.value = 0
    downloadStarted.value = false
    pollFailCount = 0
    unknownCount = 0
    groupName.value = props.defaultGroup || props.groups[0]?.group_name || 'standards'
    selectedLibs.value = libsInGroup.value.map((l) => l.id)
    void loadPreview()
  },
)

watch(selectedLibs, () => {
  if (state.value === 'form') void loadPreview()
})

// ---- 轮询（克隆 MigrationTaskDrawer：连续失败 5 次才停）----
function startPolling() {
  stopPolling()
  pollTimer = window.setInterval(() => {
    if (!taskId) return
    void fetchStatus()
  }, 1500)
}

function stopPolling() {
  if (pollTimer !== null) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
}

async function fetchStatus(): Promise<ExportStatus | null> {
  try {
    const s = await knowledgeApi.getExportStatus(taskId)
    pollFailCount = 0
    // 点「开始导出」到流请求真正到服务端之间有个空窗，status 会短暂 unknown——
    // 不能把这条当结论显示（用户会以为出错）。超过 ~20s 仍 unknown 才认账。
    if (s.status === 'unknown') {
      unknownCount += 1
      if (unknownCount > 13) {
        stopPolling()
        errorMsg.value = '任务已失效（服务可能重启过），请重新发起导出'
        state.value = 'error'
      }
      return s
    }
    unknownCount = 0
    status.value = s
    if (s.status === 'completed') {
      stopPolling()
      savedBytes.value = s.bytes_out
      state.value = 'done'
    } else if (s.status === 'failed') {
      stopPolling()
      errorMsg.value = s.error || '服务端导出失败'
      state.value = 'error'
    } else if (s.status === 'cancelled') {
      stopPolling()
      state.value = 'cancelled'
    }
    return s
  } catch (e: any) {
    pollFailCount += 1
    if (pollFailCount >= 5) {
      stopPolling()
      errorMsg.value = '状态读取失败：' + (e?.message || e)
      state.value = 'error'
    }
    return null
  }
}

// ---- 保存通道 ----
async function runExport() {
  const libs = [...selectedLibs.value]
  if (!libs.length) return
  taskId = `exp-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
  state.value = 'running'
  status.value = null
  try {
    const { ticket } = await knowledgeApi.issueExportTicket(taskId, libs)
    const url = knowledgeApi.exportStreamUrl(taskId, libs, ticket)
    startPolling()
    const picker = (window as any).showSaveFilePicker
    if (typeof picker === 'function') {
      savingMode.value = 'fsAccess'
      void streamToFilePicker(picker, url)
    } else {
      // 原生下载：带不上请求头，靠一次性 ticket 鉴权；进度由轮询给出
      savingMode.value = 'anchor'
      const a = document.createElement('a')
      a.href = url
      a.download = ''
      document.body.appendChild(a)
      a.click()
      a.remove()
      downloadStarted.value = true
    }
  } catch (e: any) {
    stopPolling()
    errorMsg.value = e?.response?.data?.detail || e?.message || String(e)
    state.value = 'error'
  }
}

/** Chromium 系：边下边写盘，可精确计数；未跑完就取消时**弃写**，不落半截文件 */
async function streamToFilePicker(picker: any, url: string) {
  const suggested = `corpus-${selectedLibs.value.join('-').slice(0, 40)}.zip`
  let writable: any = null
  try {
    const handle = await picker({ suggestedName: suggested, types: [{ description: '语料包', accept: { 'application/zip': ['.zip'] } }] })
    writable = await handle.createWritable()
    const resp = await fetch(url)
    if (!resp.ok || !resp.body) throw new Error(`HTTP ${resp.status}`)
    const reader = resp.body.getReader()
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      await writable.write(value)
      savedBytes.value += value.byteLength
    }
    // 流正常收尾不等于导出成功：取消/失败也会让连接正常闭合（chunked 无 Content-Length），
    // 必须回查终态，否则半截 zip 会被当成品保存。
    const final = await waitTerminalStatus()
    if (final === 'completed') {
      await writable.close()
    } else {
      await writable.abort()
      throw new Error(final === 'cancelled' ? '__CANCELLED__' : '导出未完成，未保存文件')
    }
  } catch (e: any) {
    if (writable) { try { await writable.abort() } catch { /* 已关闭 */ } }
    if (e?.name === 'AbortError') return
    if (e?.message === '__CANCELLED__') { state.value = 'cancelled'; return }
    void knowledgeApi.cancelExport(taskId).catch(() => {})
    errorMsg.value = `保存失败：${e?.message || e}`
    state.value = 'error'
  }
}

/** 等任务落到终态（流收尾与服务端落状态之间有毫秒级竞态） */
async function waitTerminalStatus(): Promise<string> {
  for (let i = 0; i < 10; i += 1) {
    try {
      const s = await knowledgeApi.getExportStatus(taskId)
      if (['completed', 'failed', 'cancelled'].includes(s.status)) return s.status
    } catch {
      /* 继续重试 */
    }
    await new Promise((r) => setTimeout(r, 500))
  }
  return 'unknown'
}

function onOk() {
  if (state.value === 'running') return
  if (state.value === 'form') {
    void runExport()
    return
  }
  // done / cancelled / error → 回到选择态
  state.value = 'form'
  status.value = null
  errorMsg.value = ''
  savedBytes.value = 0
  void loadPreview()
}

async function onCancel() {
  if (state.value === 'running') {
    try {
      await knowledgeApi.cancelExport(taskId)
      message.info('已请求取消，等待服务端停止…')
    } catch (e: any) {
      message.warning('取消失败：' + (e?.response?.data?.detail || e?.message || e))
    }
    return
  }
  emit('update:open', false)
}
</script>

<style scoped>
.exp-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
}
.exp-row-top {
  align-items: flex-start;
}
.exp-label {
  flex: none;
  width: 68px;
  color: var(--adm-text-secondary, rgba(255, 255, 255, 0.65));
}
.exp-libs {
  flex: 1;
  min-width: 0;
  max-height: 220px;
  overflow-y: auto;
}
.exp-lib-item {
  display: block;
  margin-left: 0;
  line-height: 24px;
}
.exp-lib-id {
  margin-left: 6px;
  font-size: 12px;
  color: var(--adm-text-tertiary, rgba(255, 255, 255, 0.35));
}
.exp-estimate {
  padding: 8px 10px;
  margin-bottom: 8px;
  background: var(--adm-fill-quaternary, rgba(255, 255, 255, 0.04));
  border-radius: 6px;
}
.exp-warn {
  margin-bottom: 8px;
}
.exp-hint {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--adm-text-tertiary, rgba(255, 255, 255, 0.45));
}
.exp-hint-dim {
  opacity: 0.75;
}
.exp-stage {
  margin: 0 0 8px;
  font-size: 14px;
}
</style>
