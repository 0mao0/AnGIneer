<template>
  <div class="public-sop-view">
    <PublicTopBar @login="loginOpen = true" />
    <AuthGate v-if="loginOpen && !authStore.isAuthed" />
    <div class="workspace">
      <SplitPanes class="panes" :initial-left-ratio="0.2" :initial-right-ratio="0.28">
        <template #left>
          <div class="left-pane">
            <PublicTreePanel
              :tree-data="tree.treeData.value"
              :loading="tree.loading.value"
              :load-error="tree.loadError.value"
              :selected-keys="tree.selectedKeys.value"
              @select="onTreeSelect"
            />
          </div>
        </template>
        <template #center>
          <div class="center-pane">
            <div v-if="!currentSop" class="empty-hint">从左侧分类选择一份公开 SOP</div>
            <SOPFlowCanvas
              v-else
              class="flow-canvas"
              :nodes="flow.nodes.value"
              :edges="flow.edges.value"
              :read-only="true"
              :selected-step-id="flow.selectedStepId.value"
              :blackboard="flow.blackboard.value"
              @step-select="onStepSelect"
            />
          </div>
        </template>
        <template #right>
          <div class="right-pane">
            <div v-if="!currentSop" class="empty-hint">从左侧分类选择一份公开 SOP</div>
            <template v-else>
              <div class="tab-switcher">
                <button
                  type="button"
                  class="tab-btn"
                  :class="{ active: rightTab === 'property' }"
                  @click="rightTab = 'property'"
                >
                  属性
                </button>
                <button
                  type="button"
                  class="tab-btn"
                  :class="{ active: rightTab === 'comment' }"
                  @click="rightTab = 'comment'"
                >
                  意见{{ commentCount > 0 ? `（${commentCount}）` : '' }}
                </button>
              </div>
              <div class="tab-body">
                <div v-show="rightTab === 'property'" class="property-pane">
                  <SOPPropertyPanel v-if="flow.selectedStep.value" :step="(flow.selectedStep.value as any)" :read-only="true" />
                  <SopMetaPanel
                    v-else-if="sopData"
                    :sop-data="sopData"
                    :all-sop-names="allSopNames"
                    :read-only="true"
                    :show-review="false"
                  />
                  <div v-else class="empty-hint">该 SOP 加载失败</div>
                </div>
                <div v-show="rightTab === 'comment'" class="comment-pane">
                  <CommentPanel
                    :sop-id="currentSop.ref_id"
                    :steps="sopSteps"
                    @submitted="onCommentSubmitted"
                    @login="loginOpen = true"
                    @count-change="commentCount = $event"
                  />
                </div>
              </div>
            </template>
          </div>
        </template>
      </SplitPanes>
    </div>
  </div>
</template>

<script setup lang="ts">
/** 公开 SOP 页（设计 §11 + 业主 10-17 改版）：左树 + 中只读画布（占满高度）+ 右「属性 | 意见」页签栏
 *  （与后台经验库右栏同构：选中步骤 → 步骤属性，未选中 → SOP 元信息；意见独立页签）。 */
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
const rightTab = ref<'property' | 'comment'>('property')
const commentCount = ref(0)

const allSopNames = computed(() =>
  tree.items.value.map((item) => item.title).filter(Boolean),
)

const sopSteps = computed(() =>
  (sopData.value?.steps || []).map((s) => ({ id: s.id, label: s.name_zh || s.name || s.id })),
)

async function openSop(item: TreeItem) {
  currentSop.value = item
  sopData.value = null
  rightTab.value = 'property'
  commentCount.value = 0
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
  // 点步骤 = 看属性：从意见页签自动切回属性（与后台经验库行为一致）
  rightTab.value = 'property'
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
    display: flex;
    flex-direction: column;
    color: var(--text-primary);

    .flow-canvas {
      flex: 1;
      min-height: 0;
    }
  }

  .right-pane {
    display: flex;
    flex-direction: column;
    height: 100%;
    min-height: 0;
    overflow: hidden;

    .tab-switcher {
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 8px 10px 6px;
      border-bottom: 1px solid var(--border-color, rgba(0, 0, 0, 0.08));
      flex-shrink: 0;
    }

    .tab-btn {
      border: none;
      background: transparent;
      color: var(--text-secondary);
      padding: 5px 10px;
      border-radius: 999px;
      cursor: pointer;
      font-size: 12px;
      transition: all 0.2s ease;

      &:hover {
        color: var(--text-primary);
      }

      &.active {
        background: rgba(24, 144, 255, 0.12);
        color: var(--primary-color);
        font-weight: 600;
      }
    }

    .tab-body {
      flex: 1;
      min-height: 0;
      overflow: hidden;
    }

    .property-pane,
    .comment-pane {
      height: 100%;
      min-height: 0;
    }
  }

  .empty-hint {
    padding: 40px 0;
    text-align: center;
    color: var(--text-tertiary);
    font-size: 13px;
  }
}
</style>
