<template>
  <!-- 三栏可调整面板组件 - 支持左右两侧面板宽度调整 -->
  <div class="split-pane" ref="containerRef">
    <div class="pane pane-left" :style="{ width: leftSize + 'px' }">
      <slot name="left" />
    </div>

    <div class="splitter splitter-left" @mousedown="startLeftResize" :class="{ resizing: isLeftResizing }" />

    <div class="pane pane-center">
      <slot name="center" />
    </div>

    <div class="splitter splitter-right" @mousedown="startRightResize" :class="{ resizing: isRightResizing }" />

    <div class="pane pane-right" :style="{ width: rightSize + 'px' }">
      <slot name="right" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, nextTick } from 'vue'

/**
 * 三栏可调整面板组件 - 支持左右两侧面板宽度拖拽调整
 */
interface Props {
  /** 左侧面板最小宽度 */
  leftMin?: number
  /** 左侧面板最大宽度 */
  leftMax?: number
  /** 右侧面板最小宽度 */
  rightMin?: number
  /** 右侧面板最大宽度 */
  rightMax?: number
  /** 左侧面板初始宽度比例（相对于容器） */
  initialLeftRatio?: number
  /** 右侧面板初始宽度比例（相对于容器） */
  initialRightRatio?: number
}

const props = withDefaults(defineProps<Props>(), {
  leftMin: 200,
  leftMax: 1000,
  rightMin: 200,
  rightMax: 1000,
  initialLeftRatio: 0.25,
  initialRightRatio: 0.25
})

const emit = defineEmits<{
  resize: [leftSize: number, rightSize: number]
}>()

const containerRef = ref<HTMLElement | null>(null)
const leftSize = ref(300)
const rightSize = ref(380)
const isLeftResizing = ref(false)
const isRightResizing = ref(false)

/** 处理左侧拖拽调整 */
const onLeftResize = (e: MouseEvent) => {
  if (!containerRef.value) return

  const containerRect = containerRef.value.getBoundingClientRect()
  let newWidth = e.clientX - containerRect.left

  newWidth = Math.max(props.leftMin, Math.min(props.leftMax, newWidth))
  leftSize.value = newWidth
  emit('resize', leftSize.value, rightSize.value)
}

/** 开始左侧拖拽 */
const startLeftResize = (e: MouseEvent) => {
  e.preventDefault()
  isLeftResizing.value = true
  document.addEventListener('mousemove', onLeftResize)
  document.addEventListener('mouseup', stopLeftResize)
}

/** 停止左侧拖拽 */
const stopLeftResize = () => {
  isLeftResizing.value = false
  document.removeEventListener('mousemove', onLeftResize)
  document.removeEventListener('mouseup', stopLeftResize)
}

/** 处理右侧拖拽调整 */
const onRightResize = (e: MouseEvent) => {
  if (!containerRef.value) return

  const containerRect = containerRef.value.getBoundingClientRect()
  let newWidth = containerRect.right - e.clientX

  newWidth = Math.max(props.rightMin, Math.min(props.rightMax, newWidth))
  rightSize.value = newWidth
  emit('resize', leftSize.value, rightSize.value)
}

/** 开始右侧拖拽 */
const startRightResize = (e: MouseEvent) => {
  e.preventDefault()
  isRightResizing.value = true
  document.addEventListener('mousemove', onRightResize)
  document.addEventListener('mouseup', stopRightResize)
}

/** 停止右侧拖拽 */
const stopRightResize = () => {
  isRightResizing.value = false
  document.removeEventListener('mousemove', onRightResize)
  document.removeEventListener('mouseup', stopRightResize)
}

/** 初始化面板尺寸 */
const initSizes = () => {
  if (!containerRef.value) return

  const containerWidth = containerRef.value.offsetWidth
  leftSize.value = Math.max(props.leftMin, Math.min(props.leftMax, containerWidth * props.initialLeftRatio))
  rightSize.value = Math.max(props.rightMin, Math.min(props.rightMax, containerWidth * props.initialRightRatio))
}

onMounted(() => {
  // 使用 nextTick 确保 DOM 已渲染完成，获取正确的容器宽度
  nextTick(() => {
    initSizes()
  })
  window.addEventListener('resize', initSizes)
})

onUnmounted(() => {
  window.removeEventListener('resize', initSizes)
  document.removeEventListener('mousemove', onLeftResize)
  document.removeEventListener('mouseup', stopLeftResize)
  document.removeEventListener('mousemove', onRightResize)
  document.removeEventListener('mouseup', stopRightResize)
})
</script>

<style lang="less" scoped>
.split-pane {
  display: flex;
  height: 100%;
  width: 100%;
  overflow: hidden;
}

.pane {
  height: 100%;
  overflow: hidden;
}

.pane-left,
.pane-right {
  flex-shrink: 0;
}

.pane-center {
  flex: 1;
  min-width: 0;
}

.splitter {
  width: 4px;
  background: transparent;
  cursor: col-resize;
  flex-shrink: 0;
  transition: background 0.2s;
  position: relative;

  &:hover,
  &.resizing {
    background: #1890ff;
  }

  &::before {
    content: '';
    position: absolute;
    left: 50%;
    top: 50%;
    transform: translate(-50%, -50%);
    width: 2px;
    height: 40px;
    background: rgba(0, 0, 0, 0.1);
    border-radius: 1px;
  }
}
</style>
