<template>
  <li class="tree-node">
    <a-tooltip
      placement="rightTop"
      :mouse-enter-delay="0.15"
      overlay-class-name="doc-block-tree-tooltip-overlay"
    >
      <template #title>
        <div class="tree-tooltip">
          <div class="tree-tooltip-text">{{ tooltipText }}</div>
          <div v-if="tooltipRichMediaHtml" class="tree-tooltip-media" v-html="tooltipRichMediaHtml" />
        </div>
      </template>
      <div
        :data-tree-node-id="nodeId"
        :class="['tree-row', { active: nodeId === activeNodeId }]"
        @click="onRowClick"
      >
        <span class="tree-toggle" @click.stop="onToggle">
          <template v-if="hasChildren">
            <RightOutlined v-if="!isExpanded" />
            <DownOutlined v-else />
          </template>
          <span v-else class="toggle-placeholder" />
        </span>
        <div class="tree-main">
          <span class="tree-text">{{ displayText }}</span>
          <span v-if="levelTag" :class="['chip', 'lv']">{{ levelTag }}</span>
          <span v-if="typeTag" class="chip">{{ typeTag }}</span>
          <span v-if="positionTag" class="chip pos">{{ positionTag }}</span>
        </div>
      </div>
    </a-tooltip>
    <ul v-if="hasChildren && isExpanded" class="tree-children">
      <DocBlocksTreeNode
        v-for="childId in children"
        :key="childId"
        :node-id="childId"
        :node-map="nodeMap"
        :children-map="childrenMap"
        :expanded-ids="expandedIds"
        :active-node-id="activeNodeId"
        :source-file-path="sourceFilePath"
        @toggle="(id) => emit('toggle', id)"
        @select="(id) => emit('select', id)"
      />
    </ul>
  </li>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { RightOutlined, DownOutlined } from '@ant-design/icons-vue'
import {
  getNodeDisplayText,
  getNodeLevelTag,
  getNodeTypeTag,
  getNodePositionTag,
  renderNodeRichMedia
} from '../../../utils/knowledge'
import type { DocBlockNode } from '../../../types/knowledge'

interface Props {
  nodeId: string
  nodeMap: Map<string, DocBlockNode>
  childrenMap: Map<string, string[]>
  expandedIds: Set<string>
  activeNodeId: string | null
  sourceFilePath?: string
}

const props = defineProps<Props>()

const emit = defineEmits<{
  toggle: [id: string]
  select: [id: string]
}>()

const node = computed(() => props.nodeMap.get(props.nodeId))

const children = computed(() => props.childrenMap.get(props.nodeId) || [])

const hasChildren = computed(() => children.value.length > 0)

const isExpanded = computed(() => props.expandedIds.has(props.nodeId))

const displayText = computed(() => getNodeDisplayText(node.value, props.nodeId))

const levelTag = computed(() => getNodeLevelTag(node.value, props.nodeMap))

const typeTag = computed(() => getNodeTypeTag(node.value))

const positionTag = computed(() => getNodePositionTag(node.value))

const tooltipText = computed(() => {
  const text = String(node.value?.plain_text || '').trim()
  return text || props.nodeId
})

const tooltipRichMediaHtml = computed(() => renderNodeRichMedia(node.value, props.sourceFilePath))

const onToggle = () => {
  emit('toggle', props.nodeId)
}

const onRowClick = () => {
  emit('select', props.nodeId)
}
</script>

<style lang="less" scoped>
.tree-node {
  margin: 4px 0;
}

.tree-row {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  padding: 5px 8px;
  border-radius: 10px;
  border: 1px solid var(--dp-pane-border, #e2e8f0);
  background: var(--dp-index-card-bg, #ffffff);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  transition: all 0.16s ease;

  &:hover {
    border-color: #bfdbfe;
    background: color-mix(in srgb, var(--dp-index-card-bg, #ffffff) 90%, #eff6ff 10%);
  }

  &.active {
    border-color: rgba(22, 119, 255, 0.8);
    box-shadow: 0 0 0 2px rgba(22, 119, 255, 0.14);
    background: color-mix(in srgb, var(--dp-index-card-bg, #ffffff) 80%, #e6f4ff 20%);
  }
}

:global(.dark-mode) .tree-row {
  &:hover {
    border-color: #1e40af;
    background: color-mix(in srgb, var(--dp-index-card-bg, #1e293b) 90%, #1e3a5f 10%);
  }
}

.tree-toggle {
  width: 16px;
  display: inline-flex;
  justify-content: center;
  align-items: center;
  color: var(--dp-sub-text, #64748b);
  font-size: 10px;
}

.toggle-placeholder {
  width: 16px;
  height: 16px;
}

.tree-children {
  list-style: none;
  margin: 0;
  padding: 0;
  margin-left: 20px;
  padding-left: 10px;
  border-left: 1px dashed var(--dp-pane-border, #cbd5e1);
}

.tree-main {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
  min-width: 0;
}

.tree-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--dp-title-text, #0f172a);
}

:global(.doc-block-tree-tooltip-overlay .ant-tooltip-inner) {
  max-width: min(720px, 78vw);
  max-height: 70vh;
  overflow: auto;
  padding: 12px;
}

.tree-tooltip {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.tree-tooltip-text {
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.6;
}

.tree-tooltip-media :deep(.media-table) {
  overflow: auto;
  max-width: 100%;
}

.tree-tooltip-media :deep(table) {
  border-collapse: collapse;
  width: 100%;
  min-width: 240px;
}

.tree-tooltip-media :deep(th),
.tree-tooltip-media :deep(td) {
  border: 1px solid rgba(148, 163, 184, 0.45);
  padding: 6px 8px;
}

.tree-tooltip-media :deep(.media-formula) {
  overflow-x: auto;
}

.tree-tooltip-media :deep(.media-image) {
  display: block;
  max-width: min(560px, 70vw);
  max-height: 320px;
  object-fit: contain;
  border-radius: 8px;
}

.chip {
  font-size: 10px;
  line-height: 1;
  padding: 3px 6px;
  border-radius: 999px;
  border: 1px solid #dbeafe;
  background: #eff6ff;
  color: #1d4ed8;
  flex-shrink: 0;

  &.lv {
    border-color: #e9d5ff;
    background: #faf5ff;
    color: #7e22ce;
  }

  &.pos {
    border-color: #fed7aa;
    background: #fff7ed;
    color: #9a3412;
  }
}

:global(.dark-mode) .chip {
  border-color: #1e3a8a;
  background: #1e293b;
  color: #93c5fd;

  &.lv {
    border-color: #581c87;
    background: #2e1065;
    color: #c4b5fd;
  }

  &.pos {
    border-color: #7c2d12;
    background: #431407;
    color: #fdba74;
  }
}
</style>
