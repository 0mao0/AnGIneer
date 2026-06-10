/**
 * SOP 步骤自定义节点组件，卡片式布局，显示步骤序号、名称、工具图标和描述。
 */
<template>
  <div
    class="sop-step-node"
    :class="{ selected: selected, hovered: hovered, dirty: isDirty }"
    @mouseenter="hovered = true"
    @mouseleave="hovered = false"
  >
    <span v-if="isDirty" class="node-dirty-dot" />
    <Handle id="top" type="target" :position="Position.Top" class="handle handle-top" />
    <Handle id="left" type="source" :position="Position.Left" class="handle handle-left" />
    <Handle id="right" type="source" :position="Position.Right" class="handle handle-right" />
    <Handle id="bottom" type="source" :position="Position.Bottom" class="handle handle-bottom" />
    <Handle id="failure" type="source" :position="Position.Right" class="handle handle-failure" />
    <button
      v-if="deletable && (hovered || selected)"
      type="button"
      class="node-delete-btn"
      title="删除步骤"
      @click.stop="emit('delete')"
    >
      <DeleteOutlined />
    </button>
    <div class="step-header">
      <span class="step-index">{{ stepIndex + 1 }}</span>
      <span class="step-name">{{ step.name || step.name_zh || step.id }}</span>
      <component :is="toolIcon" class="step-tool-icon" />
    </div>
    <div v-if="displaySegments.length" class="step-desc">
      <template v-for="(seg, idx) in displaySegments" :key="idx">
        <template v-if="seg.type === 'text'">{{ seg.text }}</template>
        <CitationInline
          v-else
          :label="seg.binding.label"
          :reference="seg.binding.reference"
          :mismatch="seg.binding.status === 'mismatch'"
          @select="emit('selectCitation', seg.binding)"
        />
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import {
  DeleteOutlined,
  CalculatorOutlined,
  TableOutlined,
  ThunderboltOutlined,
  ToolOutlined,
} from '@ant-design/icons-vue'
import { CitationInline } from '@angineer/ui-kit'
import type { CitationBinding } from '@angineer/ui-kit'
import { buildCitationSegments } from '@angineer/ui-kit/utils/citation'
import type { SopStep } from '../types/sop'

const props = defineProps<{
  id: string
  data: { step: SopStep; stepIndex: number; dirty?: boolean }
  selected?: boolean
  deletable?: boolean
}>()

const emit = defineEmits<{
  delete: []
  selectCitation: [binding: CitationBinding]
}>()

const hovered = ref(false)

const isDirty = computed(() => props.data.dirty ?? false)

const step = computed(() => props.data.step)
const stepIndex = computed(() => props.data.stepIndex)

const toolIconMap: Record<string, any> = {
  calculator: CalculatorOutlined,
  table_lookup: TableOutlined,
  auto: ThunderboltOutlined,
}

const toolIcon = computed(() => {
  return toolIconMap[step.value.execution?.tool] || ToolOutlined
})

const maxPreviewChars = 60

type Segment =
  | { type: 'text'; text: string }
  | { type: 'citation'; binding: CitationBinding }

const displaySegments = computed<Segment[]>(() => {
  const description = step.value.description
  if (!description?.content) return []

  const segments = buildCitationSegments(description) as Segment[]
  const result: Segment[] = []
  let remaining = maxPreviewChars
  for (const seg of segments) {
    if (remaining <= 0) break
    if (seg.type === 'citation') {
      const len = seg.binding.label.length
      if (len > remaining) break
      result.push(seg)
      remaining -= len
      continue
    }
    const text = seg.text.replace(/\s+/g, ' ')
    if (!text) continue
    if (text.length <= remaining) {
      result.push({ type: 'text', text })
      remaining -= text.length
      continue
    }
    result.push({ type: 'text', text: text.slice(0, Math.max(0, remaining - 3)) + '...' })
    remaining = 0
    break
  }
  return result
})
</script>

<style lang="less" scoped>
.sop-step-node {
  min-width: 180px;
  max-width: 260px;
  padding: 10px 14px;
  border-radius: 8px;
  background: var(--panel-bg, #fff);
  border: 2px solid var(--border-color, #e8e8e8);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
  transition: border-color 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease;
  cursor: pointer;
  position: relative;

  &:hover,
  &.hovered {
    border-color: rgba(24, 144, 255, 0.45);
    box-shadow: 0 8px 18px rgba(15, 23, 42, 0.08);
    transform: translateY(-1px);
  }

  &.selected {
    border-color: var(--primary-color, #1890ff);
    box-shadow:
      0 0 0 2px rgba(24, 144, 255, 0.22),
      0 10px 22px rgba(24, 144, 255, 0.16);
    transform: translateY(-1px);
  }

  &.selected .step-index,
  &.selected .step-tool-icon {
    filter: saturate(1.05);
  }

  &.selected .handle {
    background: rgba(24, 144, 255, 0.14);
    border-color: rgba(24, 144, 255, 0.45);
  }
}

.node-dirty-dot {
  position: absolute;
  top: -6px;
  left: -6px;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: #ff4d4f;
  z-index: 4;
  box-shadow: 0 0 0 2px rgba(255, 77, 79, 0.2);
}

.node-delete-btn {
  position: absolute;
  top: -10px;
  right: -10px;
  width: 22px;
  height: 22px;
  border: 1px solid rgba(255, 77, 79, 0.35);
  border-radius: 50%;
  background: #fff;
  color: #ff4d4f;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.12);
  transition: all 0.2s ease;
  z-index: 3;

  &:hover {
    background: #ff4d4f;
    color: #fff;
  }
}

.step-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.step-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--primary-color, #1890ff);
  color: #fff;
  font-size: 12px;
  font-weight: 600;
  flex-shrink: 0;
}

.step-name {
  flex: 1;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary, #262626);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.step-tool-icon {
  font-size: 14px;
  color: var(--primary-color, #1890ff);
  flex-shrink: 0;
}

.step-desc {
  margin-top: 6px;
  font-size: 11px;
  color: var(--text-secondary, #8c8c8c);
  line-height: 1.4;
}

.handle {
  width: 10px;
  height: 10px;
  border-width: 1.5px;
  background: rgba(24, 144, 255, 0.08);
  border-color: rgba(24, 144, 255, 0.28);
  box-shadow: none;
  transition: border-color 0.2s ease, background-color 0.2s ease;
}

.handle-top {
  transform: translate(-50%, -8px);
}

.handle-bottom {
  transform: translate(-50%, 8px);
}

.handle-left {
  transform: translate(-8px, -50%);
}

.handle-right {
  transform: translate(8px, -50%);
}

.handle-failure {
  width: 10px;
  height: 10px;
  background: rgba(255, 77, 79, 0.12);
  border-color: rgba(255, 77, 79, 0.5);
  transform: translate(8px, 16px);
}
</style>
