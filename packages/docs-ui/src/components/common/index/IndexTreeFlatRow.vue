<template>
  <a-tooltip
    placement="rightTop"
    :mouse-enter-delay="0.15"
    overlay-class-name="doc-block-tree-tooltip-overlay"
    @openChange="onTooltipOpenChange"
  >
    <template #title>
      <div class="tree-tooltip">
        <div v-if="tooltipTextHtml" class="tree-tooltip-text" v-html="tooltipTextHtml" />
        <div v-else-if="tooltipText" class="tree-tooltip-text">{{ tooltipText }}</div>
        <div v-if="tooltipRichMediaHtml" class="tree-tooltip-media" v-html="tooltipRichMediaHtml" />
      </div>
    </template>
    <a-dropdown :trigger="['contextmenu']">
      <div
        :data-tree-node-id="row.id"
        :class="['tree-row', { active: row.id === activeNodeId }]"
        @click="onRowClick"
        @contextmenu.prevent
      >
        <a-checkbox
          class="tree-select-checkbox"
          :checked="isChecked"
          @click.stop
          @change="onToggleCheck"
        />
        <span class="tree-toggle" @click.stop="onToggle">
          <template v-if="row.hasChildren">
            <RightOutlined v-if="!row.isExpanded" />
            <DownOutlined v-else />
          </template>
          <span v-else class="toggle-placeholder" />
        </span>
        <div class="tree-main">
          <div class="tree-meta">
            <span v-if="levelTag" :class="['chip', 'lv']">{{ levelTag }}</span>
            <span v-if="displayTextHtml" class="tree-text" v-html="displayTextHtml" />
            <span v-else-if="!suppressPlainText" class="tree-text">{{ displayText }}</span>
            <span v-if="typeTag" class="chip">{{ typeTag }}</span>
            <span v-if="positionTag" class="chip pos">{{ positionTag }}</span>
          </div>
          <div v-if="inlineRichMediaHtml" class="tree-inline-media" v-html="inlineRichMediaHtml" />
        </div>
        <a-button
          v-if="node"
          type="text"
          size="small"
          class="tree-edit-btn"
          @click.stop="onEdit"
        >
          <template #icon>
            <EditOutlined />
          </template>
        </a-button>
      </div>
      <template #overlay>
        <a-menu @click="onContextMenuClick">
          <a-sub-menu key="relevel-actions" title="调整层级">
            <a-menu-item key="promote">升一级</a-menu-item>
            <a-menu-item key="demote">降一级</a-menu-item>
            <a-menu-divider />
            <a-menu-item
              v-for="level in [1, 2, 3, 4, 5, 6]"
              :key="`set-level-${level}`"
            >
              设为 L{{ level }}
            </a-menu-item>
          </a-sub-menu>
        </a-menu>
      </template>
    </a-dropdown>
  </a-tooltip>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { RightOutlined, DownOutlined, EditOutlined } from '@ant-design/icons-vue'
import {
  getNodeDisplayText,
  getNodeLevelTag,
  getNodeTypeTag,
  getNodePositionTag,
  isNodeMathRichMediaRedundant,
  renderMarkdownInlineToHtml,
  renderNodeRichMedia,
  renderMarkdownToHtml,
  shouldSuppressNodePlainText
} from '../../../utils/knowledge'
import type { DocBlockNode } from '../../../types/knowledge'

interface FlatRow {
  id: string
  depth: number
  hasChildren: boolean
  isExpanded: boolean
}

interface Props {
  row: FlatRow
  nodeMap: Map<string, DocBlockNode>
  expandedIds: Set<string>
  activeNodeId: string | null
  selectedNodeIds?: Set<string>
  sourceFilePath?: string
}

const props = defineProps<Props>()

const emit = defineEmits<{
  toggle: [id: string]
  select: [id: string]
  edit: [id: string]
  'toggle-check': [id: string]
  'context-action': [payload: { nodeId: string; action: 'promote' | 'demote' | 'set-level'; targetLevel?: number }]
}>()

const node = computed(() => props.nodeMap.get(props.row.id))
const isChecked = computed(() => Boolean(props.selectedNodeIds?.has(props.row.id)))
const displayText = computed(() => getNodeDisplayText(node.value, props.row.id))
const suppressPlainText = computed(() => shouldSuppressNodePlainText(node.value))

const displayTextHtml = computed(() => {
  if (suppressPlainText.value) return ''
  const rawText = String(node.value?.plain_text || '').trim() || props.row.id
  return renderMarkdownInlineToHtml(rawText, props.sourceFilePath || '')
})

const levelTag = computed(() => getNodeLevelTag(node.value, props.nodeMap))
const typeTag = computed(() => getNodeTypeTag(node.value))
const positionTag = computed(() => getNodePositionTag(node.value))

const tooltipText = computed(() => {
  if (suppressPlainText.value) return ''
  const text = String(node.value?.plain_text || '').trim()
  return text || props.row.id
})

const tooltipHovered = ref(false)
const onTooltipOpenChange = (open: boolean) => {
  if (open) tooltipHovered.value = true
}

const tooltipTextHtml = computed(() => {
  if (!tooltipHovered.value) return ''
  if (suppressPlainText.value) return ''
  const text = String(node.value?.plain_text || '').trim()
  if (!text) return ''
  return renderMarkdownToHtml(text, props.sourceFilePath || '')
})

const tooltipRichMediaHtml = computed(() => {
  if (!tooltipHovered.value) return ''
  return renderNodeRichMedia(node.value, props.sourceFilePath, {
    includeMath: suppressPlainText.value || !isNodeMathRichMediaRedundant(node.value)
  })
})

const hasRichMedia = computed(() => {
  const n = node.value
  if (!n) return false
  return Boolean(
    (Array.isArray(n.rich_media_order) && n.rich_media_order.length > 0)
    || n.table_html
    || n.math_content
    || (Array.isArray(n.image_paths) && n.image_paths.length > 0)
  )
})

const inlineRichMediaHtml = computed(() => {
  if (!hasRichMedia.value) return ''
  return renderNodeRichMedia(node.value, props.sourceFilePath)
})

const onToggle = () => {
  emit('toggle', props.row.id)
}

const onRowClick = () => {
  emit('select', props.row.id)
}

const onEdit = () => {
  emit('edit', props.row.id)
}

const onToggleCheck = () => {
  emit('toggle-check', props.row.id)
}

const onContextMenuClick = ({ key }: { key: string }) => {
  if (key === 'promote' || key === 'demote') {
    emit('context-action', {
      nodeId: props.row.id,
      action: key
    })
    return
  }
  if (key.startsWith('set-level-')) {
    const targetLevel = Number(key.replace('set-level-', ''))
    if (Number.isFinite(targetLevel) && targetLevel > 0) {
      emit('context-action', {
        nodeId: props.row.id,
        action: 'set-level',
        targetLevel
      })
    }
  }
}
</script>

<style lang="less" scoped>
.tree-row {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  cursor: pointer;
  padding: 6px 8px;
  border-radius: 10px;
  border: 1px solid var(--dp-pane-border);
  background: var(--dp-index-card-bg);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  transition: all 0.16s ease;

  &:hover {
    border-color: var(--dp-hover-border);
    background: var(--dp-hover-bg);
  }

  &.active {
    border-color: var(--dp-active-border);
    box-shadow: 0 0 0 2px var(--dp-active-shadow);
    background: var(--dp-active-bg);
  }
}

.tree-select-checkbox {
  flex: 0 0 auto;
  margin-top: 2px;
}

.tree-edit-btn {
  flex: 0 0 auto;
  margin-left: 4px;
}

.tree-toggle {
  width: 16px;
  display: inline-flex;
  justify-content: center;
  align-items: center;
  color: var(--dp-sub-text);
  font-size: 10px;
}

.toggle-placeholder {
  width: 16px;
  height: 16px;
}

.tree-main {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
  min-width: 0;
}

.tree-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  min-width: 0;
}

.tree-text {
  display: block;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--dp-title-text);
}

.tree-text :deep(.katex) {
  font-size: 1em;
}

.tree-text :deep(.katex-display) {
  display: inline-block;
  margin: 0;
  vertical-align: middle;
}

.tree-inline-media {
  width: 100%;
  padding: 8px;
  border-radius: 8px;
  border: 1px solid var(--dp-pane-border);
  background: var(--dp-inline-media-bg);
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
  word-break: break-word;
  line-height: 1.6;
}

.tree-tooltip-text :deep(*:first-child) {
  margin-top: 0;
}

.tree-tooltip-text :deep(*:last-child) {
  margin-bottom: 0;
}

.tree-tooltip-text :deep(p),
.tree-tooltip-text :deep(ul),
.tree-tooltip-text :deep(ol),
.tree-tooltip-text :deep(blockquote),
.tree-tooltip-text :deep(pre),
.tree-tooltip-text :deep(table),
.tree-tooltip-text :deep(.math-block) {
  margin: 0.45em 0;
}

.tree-tooltip-text :deep(.katex-display) {
  margin: 0;
  overflow-x: auto;
  overflow-y: hidden;
}

.tree-tooltip-media :deep(.media-table) {
  overflow: auto;
  max-width: 100%;
}

.tree-inline-media :deep(.media-table) {
  overflow: auto;
  max-width: 100%;
}

.tree-tooltip-media :deep(table),
.tree-inline-media :deep(table) {
  border-collapse: collapse;
  width: 100%;
  min-width: 240px;
  table-layout: auto;
}

.tree-tooltip-media :deep(th),
.tree-tooltip-media :deep(td),
.tree-inline-media :deep(th),
.tree-inline-media :deep(td) {
  border: 1px solid rgba(148, 163, 184, 0.7) !important;
  padding: 6px 8px;
  background: transparent !important;
}

.tree-tooltip-media :deep(.media-formula),
.tree-inline-media :deep(.media-formula) {
  overflow-x: auto;
  max-width: 100%;
}

.tree-tooltip-media :deep(.katex-display),
.tree-inline-media :deep(.katex-display) {
  margin: 0;
  padding: 4px 0;
  overflow-x: auto;
  overflow-y: hidden;
}

.tree-tooltip-media :deep(.media-image),
.tree-inline-media :deep(.media-image) {
  display: block;
  width: 100%;
  max-width: 100%;
  max-height: 320px;
  object-fit: contain;
  border-radius: 8px;
  background: var(--dp-surface-bg);
}

.chip {
  font-size: 10px;
  line-height: 1;
  padding: 3px 6px;
  border-radius: 999px;
  border: 1px solid var(--chip-default-border);
  background: var(--chip-default-bg);
  color: var(--chip-default-text);
  flex-shrink: 0;

  &.lv {
    border-color: var(--chip-lv-border);
    background: var(--chip-lv-bg);
    color: var(--chip-lv-text);
  }

  &.pos {
    border-color: var(--chip-pos-border);
    background: var(--chip-pos-bg);
    color: var(--chip-pos-text);
  }
}
</style>
