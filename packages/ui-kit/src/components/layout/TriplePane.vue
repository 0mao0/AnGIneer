<template>
  <!-- 三栏可调整面板组件 - 用于知识管理页面的三栏布局 -->
  <div class="triple-pane" ref="containerRef">
    <!-- 左侧面板 -->
    <div
      class="pane pane-left"
      :style="{ width: leftWidth + 'px', minWidth: minWidth + 'px' }"
    >
      <slot name="left" />
    </div>

    <!-- 左侧分隔条 -->
    <div
      class="resizer resizer-left"
      @mousedown="startResize($event, 'left')"
      :class="{ resizing: resizing === 'left' }"
    />

    <!-- 中间面板 -->
    <div
      class="pane pane-center"
      :style="{ width: centerWidth + 'px', minWidth: centerMinWidth + 'px' }"
    >
      <slot name="center" />
    </div>

    <!-- 右侧分隔条 -->
    <div
      class="resizer resizer-right"
      @mousedown="startResize($event, 'right')"
      :class="{ resizing: resizing === 'right' }"
    />

    <!-- 右侧面板 -->
    <div
      class="pane pane-right"
      :style="{ flex: 1, minWidth: minWidth + 'px' }"
    >
      <slot name="right" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'

/**
 * 三栏可调整面板组件
 * 支持左右两个分隔条拖拽调整宽度
 */
interface Props {
  /** 左侧面板初始宽度 */
  leftInitialWidth?: number
  /** 中间面板初始宽度 */
  centerInitialWidth?: number
  /** 面板最小宽度（像素） */
  minWidth?: number
  /** 中间面板最小宽度（像素） */
  centerMinWidth?: number
  /** 左侧面板最大宽度比例（相对于容器） */
  leftMaxRatio?: number
  /** 中间面板最大宽度比例（相对于容器） */
  centerMaxRatio?: number
}

const props = withDefaults(defineProps<Props>(), {
  leftInitialWidth: 350,
  centerInitialWidth: 700,
  minWidth: 100,
  centerMinWidth: 300,
  leftMaxRatio: 0.4,
  centerMaxRatio: 0.7
})

const emit = defineEmits<{
  resize: [panel: 'left' | 'center', width: number]
}>()

const containerRef = ref<HTMLElement | null>(null)
const leftWidth = ref(props.leftInitialWidth)
const centerWidth = ref(props.centerInitialWidth)
const resizing = ref<'left' | 'right' | null>(null)

let startX = 0
let startLeftWidth = 0
let startCenterWidth = 0

/** 开始拖拽调整大小 */
const startResize = (e: MouseEvent, panel: 'left' | 'right') => {
  e.preventDefault()
  resizing.value = panel
  startX = e.clientX
  startLeftWidth = leftWidth.value
  startCenterWidth = centerWidth.value

  document.addEventListener('mousemove', handleResize)
  document.addEventListener('mouseup', stopResize)
}

/** 处理拖拽调整 */
const handleResize = (e: MouseEvent) => {
  if (!containerRef.value || !resizing.value) return

  const containerWidth = containerRef.value.offsetWidth
  const delta = e.clientX - startX

  if (resizing.value === 'left') {
    // 调整左侧面板
    const maxWidth = containerWidth * props.leftMaxRatio
    const newWidth = Math.max(props.minWidth, Math.min(maxWidth, startLeftWidth + delta))
    leftWidth.value = newWidth
    emit('resize', 'left', newWidth)
  } else if (resizing.value === 'right') {
    // 调整中间面板（右侧分隔条控制中间面板宽度）
    const maxWidth = containerWidth * props.centerMaxRatio
    const minCenterWidth = containerWidth * 0.3
    const newWidth = Math.max(minCenterWidth, Math.min(maxWidth, startCenterWidth + delta))
    centerWidth.value = newWidth
    emit('resize', 'center', newWidth)
  }
}

/** 停止拖拽 */
const stopResize = () => {
  resizing.value = null
  document.removeEventListener('mousemove', handleResize)
  document.removeEventListener('mouseup', stopResize)
}

onUnmounted(() => {
  document.removeEventListener('mousemove', handleResize)
  document.removeEventListener('mouseup', stopResize)
})
</script>

<style lang="less" scoped>
.triple-pane {
  display: flex;
  width: 100%;
  height: 100%;
  overflow: hidden;

  .pane {
    display: flex;
    flex-direction: column;
    overflow: hidden;

    &-left {
      flex-shrink: 0;
    }

    &-center {
      flex-shrink: 0;
    }

    &-right {
      flex: 1;
    }
  }

  .resizer {
    width: 4px;
    background: #e8e8e8;
    cursor: col-resize;
    transition: background 0.2s;
    flex-shrink: 0;

    &:hover,
    &.resizing {
      background: #1890ff;
    }
  }
}

// Dark mode
:global(.dark-mode) {
  .triple-pane {
    .resizer {
      background: #303030;

      &:hover,
      &.resizing {
        background: #1890ff;
      }
    }
  }
}
</style>
