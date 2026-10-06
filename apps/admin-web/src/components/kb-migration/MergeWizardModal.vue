<template>
  <a-modal
    :open="props.open"
    :title="`合并知识库：${props.library?.name || ''} → 并入另一个库`"
    :width="720"
    :ok-text="current === 0 ? '下一步' : '确认合并'"
    :cancel-text="current === 1 ? '上一步' : '取消'"
    :ok-button-props="{ disabled: okDisabled, danger: current === 1, loading: submitting }"
    :mask-closable="false"
    @update:open="(v: boolean) => emit('update:open', v)"
    @cancel="onCancel"
    @ok="onOk"
  >
    <!-- ① 选目标库 -->
    <template v-if="current === 0">
      <p class="wiz-lead">
        本库 {{ sourceDocsLine }}将全部并入下面选定的库，合并完成后本库停用（数据不删，可 7 天内回滚）。
      </p>
      <a-form layout="vertical">
        <a-form-item label="并入目标库（同组）" required>
          <a-select
            v-model:value="targetId"
            style="width: 100%"
            placeholder="选择要并入的库"
            :options="targetOptions"
            :not-found-content="peerLibraries.length ? undefined : '当前组没有其它可用库'"
          />
        </a-form-item>
      </a-form>
    </template>

    <!-- ② 预览 + 强确认（克隆删库四件套） -->
    <template v-else-if="current === 1">
      <a-spin :spinning="previewing">
        <table class="mig-preview-table" v-if="preview">
          <thead>
            <tr><th>迁移内容</th><th>合并前</th><th>合并后</th></tr>
          </thead>
          <tbody>
            <tr>
              <td>文档（{{ props.library?.name }}）</td>
              <td>{{ preview.counts.docs.source_before }} 篇</td>
              <td>0 篇（本库停用）</td>
            </tr>
            <tr>
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
                {{ preview.counts.graph.entities }} 个实体、{{ preview.counts.graph.relations }} 条关系迁入；
                两库同名实体会自动归并
              </td>
            </tr>
            <tr v-if="preview.eval_refs.datasets.length">
              <td>题集引用</td>
              <td colspan="2">
                {{ evalRefsLine }}——题集与题目不改动，合并后请确认题集指向
              </td>
            </tr>
          </tbody>
        </table>
        <p class="wiz-merge-warning">
          合并后本库停用；期间目标库暂停入库，读与问答不受影响；7 天内可一键回滚。
        </p>
        <p>请输入被合并库的完整名称确认：</p>
        <p class="wiz-merge-name">{{ props.library?.name }}</p>
        <a-input-group compact class="wiz-fill-group">
          <a-input
            v-model:value="confirmInput"
            :placeholder="props.library?.name || ''"
            class="wiz-fill-input"
          />
          <a-button
            class="wiz-fill-btn"
            title="点击自动填入完整库名，再次确认后即可合并"
            @click="confirmInput = props.library?.name || ''"
          >
            一键填入
          </a-button>
        </a-input-group>
      </a-spin>
    </template>
  </a-modal>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { knowledgeApi, type LibraryVolume, type MigrationPreview } from '@/api/knowledge'
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
const previewing = ref(false)
const submitting = ref(false)
const targetId = ref<string | undefined>(undefined)
const preview = ref<MigrationPreview | null>(null)
const confirmInput = ref('')
const volumes = ref<LibraryVolume[]>([])

/** 同组、非 default、非自身的可并库；迁移中/停用库排除（volumes 未到位时先放行，预览端会再拦） */
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

const sourceDocsLine = computed(() => {
  const v = volumes.value.find((x) => x.library_id === props.library?.id)
  return v ? `${v.docs} 篇` : ''
})

const evalRefsLine = computed(() => {
  const refs = preview.value?.eval_refs
  if (!refs || !refs.datasets.length) return ''
  const titles = refs.datasets.map((d) => d.title).join('、')
  const onMoved = refs.questions_on_moved_docs ?? 0
  return `被合并库涉及 ${refs.datasets.length} 个题集（${titles}），共 ${refs.question_count} 题，其中 ${onMoved} 题用到迁出的文档`
})

const okDisabled = computed(() => {
  if (current.value === 0) return !targetId.value || previewing.value
  return (
    !preview.value ||
    submitting.value ||
    confirmInput.value.trim() !== (props.library?.name || '').trim()
  )
})

watch(
  () => props.open,
  (open) => {
    if (!open || !props.library) return
    current.value = 0
    targetId.value = undefined
    preview.value = null
    confirmInput.value = ''
    void loadVolumes()
    if (store.libraries.length === 0) void store.loadLibraries()
  },
)

async function loadVolumes() {
  try {
    volumes.value = (await knowledgeApi.getLibraryVolumes()).volumes
  } catch {
    // 体量看板失败不阻塞向导：下拉只显库名
  }
}

async function makePreview() {
  if (!props.library || !targetId.value) return
  previewing.value = true
  preview.value = null
  try {
    preview.value = (await knowledgeApi.previewMigration({
      op: 'merge',
      source_library_id: props.library.id,
      target_library_id: targetId.value,
    })) as unknown as MigrationPreview
  } catch (e: any) {
    message.error(e.message || '预览失败')
    current.value = 0
  } finally {
    previewing.value = false
  }
}

async function doSubmit() {
  if (!props.library || !preview.value || !targetId.value) return
  submitting.value = true
  try {
    const resp = (await knowledgeApi.submitMigration({
      op: 'merge',
      source_library_id: props.library.id,
      target_library_id: targetId.value,
      preview_digest: preview.value.digest,
    })) as unknown as { task_id: string }
    message.success('合并任务已提交')
    emit('submitted', resp.task_id)
    emit('update:open', false)
  } catch (e: any) {
    if (String(e.message || '').includes('预览已过期')) {
      message.warning('库内容有变化，预览已过期，已自动重新预览')
      confirmInput.value = ''
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
    if (!targetId.value) return
    current.value = 1
    void makePreview()
    return
  }
  void doSubmit()
}

function onCancel() {
  if (current.value === 1 && !submitting.value) {
    current.value = 0
    return
  }
  emit('update:open', false)
}
</script>

<style scoped>
.wiz-lead {
  margin-bottom: 12px;
}
.wiz-merge-warning {
  color: var(--error-color, #ff4d4f);
  margin: 12px 0 8px;
}
.wiz-merge-name {
  font-weight: 600;
  word-break: break-all;
  margin-bottom: 8px;
}
.wiz-fill-group {
  display: flex;
  width: 100%;
}
.wiz-fill-input {
  flex: 1;
  min-width: 0;
}
.wiz-fill-btn {
  color: var(--text-secondary, rgba(0, 0, 0, 0.45));
  background: var(--bg-secondary, #fafafa);
  border-color: var(--border-color, #d9d9d9);
}
.wiz-fill-btn:hover {
  color: var(--primary-color, #1677ff);
  border-color: var(--primary-color, #1677ff);
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
