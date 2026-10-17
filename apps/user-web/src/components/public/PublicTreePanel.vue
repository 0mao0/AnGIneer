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
      :expand-selected-path="true"
      :default-selected-keys="selectedKeys"
      :dark="isDark"
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
      <!-- 只读树：覆盖 SmartTree 默认行内操作槽（重命名/查看/删除按钮），公开面一律不给
          写操作入口（业主 2026-10-15：这些都不允许编辑删除，按钮全部禁止）。
          槽里必须放一个真实元素——只写注释/空白时 Vue 视为空槽、会回退渲染默认按钮 -->
      <template #actions>
        <span class="actions-none" aria-hidden="true" />
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
import { useTheme } from '@angineer/ui-kit'
import type { CommunityTreeNode } from '@/composables/useCommunityTree'

defineProps<{
  treeData: CommunityTreeNode[]
  loading: boolean
  loadError: string
  /** 选中高亮通道（SmartTree defaultSelectedKeys），宿主传树数据源里当前选中的 key */
  selectedKeys?: string[]
}>()

// 暗色样式挂在 SmartTree 的 dark 属性上（组件内 .dark-mode 作用域），宿主不传=整段暗色失效
const { isDark } = useTheme()

const emit = defineEmits<{
  (e: 'select', row: CommunityTreeNode | null): void
}>()

// 默认全折叠（进页只出一级目录）：分类树会继续变深，全展开渲染会拖卡。
// 进页自动选中首个条目时，靠 SmartTree 的 expand-selected-path 只展开它所在的祖先链并高亮（selectedKeys）。
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

  // 只读：行内操作槽的占位元素不占位（见模板 #actions）
  .actions-none {
    display: none;
  }

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
