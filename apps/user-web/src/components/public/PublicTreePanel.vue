<template>
  <div class="public-tree-panel">
    <SmartTree
      :tree-data="treeData"
      :show-search="true"
      search-placeholder="搜索分类或条目..."
      :show-add-root-folder="false"
      :draggable="false"
      :allow-add-file="false"
      :allow-batch-delete="false"
      :show-status="false"
      :loading="loading"
      :virtual="true"
      :height="treeHeight"
      :default-expanded-keys="rootKeys"
      empty-text="该分类暂无公开内容"
      @select="onSelect"
    >
      <template #title="{ node }">
        <span class="tree-title">
          <span class="tree-title-text">{{ node.title }}</span>
          <span v-if="node.isFolder" class="folder-count">({{ node.communityCount ?? 0 }})</span>
          <span v-if="node.communityItem?.origin === 'user'" class="user-badge" title="网友投稿">投稿</span>
          <span v-else-if="node.communityItem?.kind === 'dataset' && node.communityItem.question_count != null" class="count-badge">
            {{ node.communityItem.question_count }}
          </span>
        </span>
      </template>
    </SmartTree>
    <div v-if="loadError" class="tree-error">{{ loadError }}</div>
  </div>
</template>

<script setup lang="ts">
/** 公开两页左树薄封装（设计 §7.2）：SmartTree + 虚拟滚动 + 投稿徽标 slot。
 *  只读树：增删/拖拽/文件操作全部关闭。 */
import { computed } from 'vue'
import { SmartTree, type SmartTreeNode } from '@angineer/smartree'
import type { CommunityTreeNode } from '@/composables/useCommunityTree'

const props = defineProps<{
  treeData: CommunityTreeNode[]
  loading: boolean
  loadError: string
}>()

const emit = defineEmits<{
  (e: 'select', row: CommunityTreeNode | null): void
}>()

// 默认展开全部目录（含二层子类）：分类是这两页的主信息，折叠起来只剩一排骨架
const allFolderKeys = (rows: CommunityTreeNode[]): string[] =>
  rows.flatMap((r) => (r.isFolder ? [r.key, ...allFolderKeys(r.children || [])] : []))
const rootKeys = computed(() => allFolderKeys(props.treeData))
const treeHeight = computed(() => Math.max(320, window.innerHeight - 160))

// SmartTree 的 select 事件按基类型 SmartTreeNode[] 回传（传进去的就是本页的行对象，取回即本型）
function onSelect(_keys: string[], nodes: SmartTreeNode[]) {
  emit('select', (nodes[0] as CommunityTreeNode) || null)
}
</script>

<style lang="less" scoped>
.public-tree-panel {
  height: 100%;
  overflow: hidden;

  .tree-title {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    min-width: 0;

    .tree-title-text {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
  }

  .user-badge {
    flex-shrink: 0;
    font-size: 10px;
    line-height: 16px;
    padding: 0 5px;
    border-radius: 8px;
    color: var(--primary-color);
    border: 1px solid var(--primary-color);
  }

  .count-badge {
    flex-shrink: 0;
    font-size: 11px;
    color: var(--text-tertiary);
  }

  .folder-count {
    flex-shrink: 0;
    font-size: 12px;
    color: var(--text-tertiary);
  }

  .tree-error {
    padding: 8px 12px;
    font-size: 12px;
    color: var(--ant-error-color, #ff4d4f);
  }
}
</style>
