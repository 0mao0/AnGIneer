<template>
  <a-modal
    :open="open"
    title="导入知识库语料包"
    width="680px"
    :footer="null"
    :mask-closable="state !== 'applying'"
    @cancel="close"
    @ok="close"
  >
    <div class="imp-body">
      <!-- 1. 选包 + 目标组 -->
      <template v-if="state === 'form'">
        <div class="imp-drop" :class="{ 'is-over': dragOver }"
             @click="fileInput?.click()"
             @dragover.prevent="dragOver = true"
             @dragleave.prevent="dragOver = false"
             @drop.prevent="onDrop">
          <input ref="fileInput" type="file" accept=".zip" hidden @change="onFilePicked" />
          <p class="imp-drop-title">点击或拖拽 v2 语料包（.zip）</p>
          <p v-if="file" class="imp-file">{{ file.name }} · {{ formatBytes(file.size) }}</p>
          <p v-else class="imp-hint">外层大包或单库小包均可；v1 旧包不再支持</p>
        </div>

        <div class="imp-row">
          <span class="imp-label">目标组</span>
          <a-select v-model:value="groupChoice" class="imp-grow" :options="groupOptions" />
        </div>
        <div v-if="groupChoice === '__new__'" class="imp-new-group">
          <a-input v-model:value="newGroup" placeholder="组 slug（小写字母/数字/_/-）" />
          <a-input v-model:value="newGroupDisplay" placeholder="显示名（可选）" />
        </div>

        <a-checkbox v-model:checked="withVectors" class="imp-check">
          包含向量快照（关闭则导入后该库不可检索，需重建向量）
        </a-checkbox>

        <a-alert
          type="info"
          show-icon
          class="imp-note"
          message="包内 files/ 根必须与目标组一致（知识包用知识组、evals 包用 evals 组）；应用阶段不可取消。"
        />

        <div class="imp-footer">
          <a-button @click="close">取消</a-button>
          <a-button type="primary" :disabled="!file" :loading="uploading" @click="startUpload">
            上传并预检
          </a-button>
        </div>
      </template>

      <!-- 2. 上传 -->
      <template v-else-if="state === 'uploading'">
        <div class="imp-center">
          <a-progress type="circle" :percent="uploadPercent" />
          <p class="imp-stage">正在上传并预检……</p>
          <p class="imp-hint">预检只读，不会写目标库</p>
        </div>
      </template>

      <!-- 3. 预检结果 -->
      <template v-else-if="state === 'preview' && status">
        <a-alert type="success" show-icon message="预检通过，请选择要导入的库" class="imp-note" />
        <div class="imp-libs">
          <div v-for="lib in previewLibraries" :key="lib.library_id" class="imp-lib">
            <a-checkbox :checked="selected.includes(lib.library_id)"
                        @change="toggleLib(lib.library_id)" />
            <div class="imp-lib-main">
              <div class="imp-lib-name">{{ lib.name }}</div>
              <div class="imp-lib-meta">
                {{ lib.library_id }} · {{ lib.group_name }} ·
                {{ lib.counts?.docs ?? 0 }} docs / {{ lib.counts?.chunks ?? 0 }} chunks /
                {{ lib.counts?.vectors ?? 0 }} vectors · {{ formatBytes(lib.bytes) }}
              </div>
            </div>
          </div>
        </div>

        <div class="imp-row">
          <span class="imp-label">目标组</span>
          <a-select v-model:value="groupChoice" class="imp-grow" :options="groupOptions" />
        </div>
        <div v-if="groupChoice === '__new__'" class="imp-new-group">
          <a-input v-model:value="newGroup" placeholder="组 slug" />
          <a-input v-model:value="newGroupDisplay" placeholder="显示名（可选）" />
        </div>

        <div class="imp-footer">
          <a-button @click="reset">重新选择</a-button>
          <a-button type="primary" :disabled="!selected.length"
                    :loading="applying" @click="startApply">
            开始导入（{{ selected.length }} 个库）
          </a-button>
        </div>
      </template>

      <!-- 4. 应用 -->
      <template v-else-if="state === 'applying' && status">
        <div class="imp-center">
          <a-spin size="large" />
          <p class="imp-stage">{{ status.message || '正在导入' }}</p>
          <a-progress :percent="100" status="active" :show-info="false" />
          <p class="imp-hint">应用阶段不可取消；失败会保留暂存包供排障</p>
        </div>
      </template>

      <!-- 5. 完成 / 失败 -->
      <template v-else-if="state === 'done'">
        <a-result status="success" title="导入完成"
                  :sub-title="`已导入：${status?.applied_libraries?.join('、') || selected.join('、')}`">
          <template #extra>
            <a-button type="primary" @click="finish">完成</a-button>
          </template>
        </a-result>
      </template>
      <template v-else-if="state === 'error'">
        <a-result status="error" title="导入失败" :sub-title="errorMsg">
          <template #extra>
            <a-button @click="reset">重新选择</a-button>
            <a-button type="primary" @click="close">关闭</a-button>
          </template>
        </a-result>
      </template>
    </div>
  </a-modal>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { knowledgeApi, type ImportLibraryPreview, type ImportStatus, type LibraryGroupItem } from '@/api/knowledge'
import { groupLabel } from '../kb-group-label'

const props = withDefaults(defineProps<{
  open: boolean
  groups: LibraryGroupItem[]
  defaultGroup?: string
}>(), { defaultGroup: '' })

const emit = defineEmits<{
  (e: 'update:open', v: boolean): void
  (e: 'done'): void
}>()

type State = 'form' | 'uploading' | 'preview' | 'applying' | 'done' | 'error'
const state = ref<State>('form')
const fileInput = ref<HTMLInputElement | null>(null)
const file = ref<File | null>(null)
const dragOver = ref(false)
const uploading = ref(false)
const uploadPercent = ref(0)
const applying = ref(false)
const errorMsg = ref('')
const status = ref<ImportStatus | null>(null)
const selected = ref<string[]>([])
const withVectors = ref(true)
const groupChoice = ref('')
const newGroup = ref('')
const newGroupDisplay = ref('')
let pollTimer: number | null = null

const previewLibraries = computed<ImportLibraryPreview[]>(() => status.value?.preview?.libraries || [])

const groupOptions = computed(() => {
  const seen = new Set<string>()
  const out: { value: string; label: string }[] = []
  for (const g of props.groups || []) {
    if (!g.group_name || seen.has(g.group_name)) continue
    seen.add(g.group_name)
    out.push({ value: g.group_name, label: groupLabel(g.group_name, props.groups) })
  }
  out.push({ value: '__new__', label: '＋ 新建组' })
  return out
})

function formatBytes(n: number): string {
  if (!n) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let v = n
  let i = 0
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i += 1 }
  return `${v.toFixed(i ? 1 : 0)} ${units[i]}`
}

function resolvedGroup(): string {
  return groupChoice.value === '__new__' ? newGroup.value.trim() : groupChoice.value
}

function onFilePicked(e: Event) {
  const input = e.target as HTMLInputElement
  const f = input.files?.[0]
  if (!f) return
  if (!f.name.toLowerCase().endsWith('.zip')) {
    message.error('只接受 .zip 语料包')
    return
  }
  file.value = f
  errorMsg.value = ''
}

function onDrop(e: DragEvent) {
  dragOver.value = false
  const f = e.dataTransfer?.files?.[0]
  if (!f) return
  if (!f.name.toLowerCase().endsWith('.zip')) {
    message.error('只接受 .zip 语料包')
    return
  }
  file.value = f
}

async function startUpload() {
  if (!file.value) return
  const g = resolvedGroup()
  if (g === '__new__' || (groupChoice.value === '__new__' && !/^[a-z][a-z0-9_-]{1,31}$/.test(g))) {
    message.error('新组 slug 须小写字母开头，2–32 位')
    return
  }
  uploading.value = true
  uploadPercent.value = 0
  state.value = 'uploading'
  try {
    const resp = await knowledgeApi.uploadImport(
      file.value,
      {
        groupName: groupChoice.value === '__new__' ? g : groupChoice.value,
        groupDisplayName: groupChoice.value === '__new__' ? newGroupDisplay.value.trim() : '',
        withVectors: withVectors.value,
      },
      (p) => { uploadPercent.value = p },
    )
    status.value = resp
    selected.value = (resp.preview?.libraries || []).map((l) => l.library_id)
    const suggested = resp.group_name || resp.preview?.libraries?.[0]?.group_name || props.defaultGroup
    groupChoice.value = suggested && groupOptions.value.some((o) => o.value === suggested)
      ? suggested
      : (groupOptions.value[0]?.value || '')
    state.value = 'preview'
  } catch (e: any) {
    errorMsg.value = e?.response?.data?.detail || e?.message || String(e)
    state.value = 'error'
  } finally {
    uploading.value = false
  }
}

function toggleLib(id: string) {
  selected.value = selected.value.includes(id)
    ? selected.value.filter((x) => x !== id)
    : [...selected.value, id]
}

async function startApply() {
  if (!status.value || !selected.value.length) return
  const g = resolvedGroup()
  if (!g || g === '__new__') {
    message.error('请选择目标组')
    return
  }
  applying.value = true
  try {
    status.value = await knowledgeApi.applyImport(status.value.task_id, {
      group_name: g,
      group_display_name: groupChoice.value === '__new__' ? newGroupDisplay.value.trim() : '',
      libraries: selected.value,
    })
    state.value = 'applying'
    startPolling()
  } catch (e: any) {
    applying.value = false
    errorMsg.value = e?.response?.data?.detail || e?.message || String(e)
    state.value = 'error'
  }
}

function startPolling() {
  stopPolling()
  pollTimer = window.setInterval(fetchStatus, 1200)
}

function stopPolling() {
  if (pollTimer !== null) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
}

async function fetchStatus() {
  if (!status.value) return
  try {
    const s = await knowledgeApi.getImportStatus(status.value.task_id)
    status.value = s
    if (s.status === 'completed') {
      stopPolling()
      applying.value = false
      state.value = 'done'
    } else if (s.status === 'failed') {
      stopPolling()
      applying.value = false
      errorMsg.value = s.error || '服务端导入失败'
      state.value = 'error'
    } else {
      state.value = 'applying'
    }
  } catch (e: any) {
    stopPolling()
    applying.value = false
    errorMsg.value = e?.response?.data?.detail || e?.message || String(e)
    state.value = 'error'
  }
}

async function close() {
  if (state.value === 'applying') return
  if (status.value && state.value === 'preview') {
    void knowledgeApi.deleteImport(status.value.task_id).catch(() => {})
  }
  reset()
  emit('update:open', false)
}

function reset() {
  stopPolling()
  status.value = null
  file.value = null
  selected.value = []
  errorMsg.value = ''
  uploadPercent.value = 0
  uploading.value = false
  applying.value = false
  state.value = 'form'
  if (fileInput.value) fileInput.value.value = ''
}

function finish() {
  emit('done')
  emit('update:open', false)
  reset()
}

watch(() => props.open, (open) => {
  if (!open) return
  reset()
  groupChoice.value = props.defaultGroup && groupOptions.value.some((o) => o.value === props.defaultGroup)
    ? props.defaultGroup
    : (groupOptions.value[0]?.value || '')
})

onBeforeUnmount(stopPolling)
</script>

<style scoped>
.imp-body { min-height: 220px; }
.imp-drop {
  border: 1px dashed rgba(255, 255, 255, 0.22);
  border-radius: 10px;
  padding: 28px 16px;
  text-align: center;
  cursor: pointer;
  transition: border-color .2s, background .2s;
}
.imp-drop:hover, .imp-drop.is-over { border-color: #1677ff; background: rgba(22, 119, 255, 0.06); }
.imp-drop-title { margin: 0 0 6px; font-size: 14px; }
.imp-file { margin: 0; color: #1677ff; font-weight: 600; }
.imp-hint { margin: 4px 0 0; color: rgba(255, 255, 255, 0.45); font-size: 12px; }
.imp-row { display: flex; align-items: center; gap: 12px; margin-top: 16px; }
.imp-label { width: 64px; color: rgba(255, 255, 255, 0.65); font-size: 13px; }
.imp-grow { flex: 1; }
.imp-new-group { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 8px; }
.imp-check { margin-top: 16px; }
.imp-note { margin-top: 14px; }
.imp-footer { display: flex; justify-content: flex-end; gap: 8px; margin-top: 20px; }
.imp-center { display: flex; flex-direction: column; align-items: center; gap: 12px; padding: 24px 0; }
.imp-stage { margin: 0; font-size: 14px; }
.imp-libs { max-height: 280px; overflow: auto; margin-top: 12px; display: grid; gap: 8px; }
.imp-lib {
  display: flex; gap: 10px; align-items: flex-start;
  padding: 10px 12px; border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 8px;
}
.imp-lib-main { min-width: 0; }
.imp-lib-name { font-weight: 600; }
.imp-lib-meta { margin-top: 3px; color: rgba(255, 255, 255, 0.55); font-size: 12px; }
</style>
