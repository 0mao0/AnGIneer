<template>
  <div class="public-sop-view">
    <PublicTopBar @login="loginOpen = true" />
    <AuthGate v-if="loginOpen && !authStore.isAuthed" />
    <div class="workspace">
      <SplitPanes class="panes" :initial-left-ratio="0.2" :right-collapsible="false" :show-right-pane="false">
        <template #left>
          <div class="left-pane">
            <PublicTreePanel
              :tree-data="tree.treeData.value"
              :loading="tree.loading.value"
              :load-error="tree.loadError.value"
              @select="onTreeSelect"
            />
          </div>
        </template>
        <template #center>
          <div class="center-pane">
            <div v-if="!currentSop" class="empty-hint">从左侧分类选择一份公开 SOP</div>
            <template v-else>
              <div class="sop-canvas-block">
                <SOPFlowCanvas
                  :nodes="flow.nodes.value"
                  :edges="flow.edges.value"
                  :read-only="true"
                  :selected-step-id="flow.selectedStepId.value"
                  :blackboard="flow.blackboard.value"
                  @step-select="onStepSelect"
                />
              </div>
              <div v-if="flow.selectedStep.value" class="sop-step-panel">
                <SOPPropertyPanel :step="(flow.selectedStep.value as any)" :read-only="true" />
              </div>
              <div v-if="sopData" class="sop-meta-block">
                <SopMetaPanel :sop-data="sopData" :all-sop-names="allSopNames" :read-only="true" :show-review="false" />
              </div>
              <CommentPanel
                :sop-id="currentSop.ref_id"
                :steps="sopSteps"
                @submitted="onCommentSubmitted"
                @login="loginOpen = true"
              />
            </template>
          </div>
        </template>
      </SplitPanes>
    </div>
  </div>
</template>

<script setup lang="ts">
/** 公开 SOP 页（设计 §11 右栏线框）：只读流程画布 + 只读步骤属性 + 元信息（无审核块）+ 意见面板。 */
import { computed, onMounted, ref } from 'vue'
import { SplitPanes } from '@angineer/ui-kit'
import { SOPFlowCanvas, SOPPropertyPanel, SopMetaPanel, normalizeSopData, useSopFlow } from '@angineer/sop-ui'
import type { SopData } from '@angineer/sop-ui'
import PublicTopBar from '@/components/PublicTopBar.vue'
import AuthGate from '@/components/AuthGate.vue'
import PublicTreePanel from '@/components/public/PublicTreePanel.vue'
import CommentPanel from '@/components/public/CommentPanel.vue'
import { useCommunityTree, type CommunityTreeNode } from '@/composables/useCommunityTree'
import { communityApi, type TreeItem } from '@/api/community'
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()
const tree = useCommunityTree('sop')
const flow = useSopFlow()
const loginOpen = ref(false)

const currentSop = ref<TreeItem | null>(null)
const sopData = ref<SopData | null>(null)

const allSopNames = computed(() =>
  tree.items.value.map((item) => item.title).filter(Boolean),
)

const sopSteps = computed(() =>
  (sopData.value?.steps || []).map((s) => ({ id: s.id, label: s.name_zh || s.name || s.id })),
)

async function openSop(item: TreeItem) {
  currentSop.value = item
  sopData.value = null
  flow.loadFromSopData({ id: '', name_zh: '', steps: [] } as unknown as SopData)
  try {
    const raw = await communityApi.getSop(item.ref_id)
    const data = normalizeSopData(raw as any)
    sopData.value = data
    flow.loadFromSopData(data)
  } catch {
    sopData.value = null
  }
}

function onTreeSelect(row: CommunityTreeNode | null) {
  tree.select(row)
  const item = row?.communityItem || null
  if (item) void openSop(item)
  else currentSop.value = null
}

function onStepSelect(nodeId: string) {
  flow.selectStep(nodeId)
}

function onCommentSubmitted() {
  // 本版只收不审：意见提交后无需刷新（面板本地回显）
}

onMounted(async () => {
  if (!authStore.isAuthed) void authStore.enterGuestMode()
  await tree.reload()
  const first = tree.selectedItem.value
  if (first) void openSop(first)
})
</script>

<style lang="less" scoped>
.public-sop-view {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--bg-primary);

  .workspace {
    flex: 1;
    min-height: 0;

    .panes {
      height: 100%;
    }
  }

  .left-pane {
    height: 100%;
    padding: 8px 4px;
  }

  .center-pane {
    height: 100%;
    overflow-y: auto;
    padding: 16px 24px;
    color: var(--text-primary);
  }

  .empty-hint {
    padding: 40px 0;
    text-align: center;
    color: var(--text-tertiary);
    font-size: 13px;
  }

  .sop-canvas-block {
    height: 360px;
    border: 1px solid var(--border-color, rgba(0, 0, 0, 0.08));
    border-radius: 8px;
    overflow: hidden;
  }

  .sop-step-panel {
    margin-top: 12px;
  }

  .sop-meta-block {
    margin-top: 12px;
  }
}
</style>
