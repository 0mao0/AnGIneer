<template>
  <!-- 三栏可调整面板组件 - 支持左右两侧面板宽度拖拽调整和收起 -->
  <div
    class="split-pane"
    ref="containerRef"
    :class="{ 'left-collapsed': leftCollapsed, 'right-collapsed': rightCollapsed }"
  >
    <!-- 左侧面板 -->
    <div
      v-show="!leftCollapsed"
      class="pane pane-left"
      :style="{ width: effectiveLeftWidth + 'px' }"
    >
      <slot name="left" />
    </div>

    <!-- 左侧收起/展开细条入口（仅在收起后显示） -->
    <div
      v-if="leftCollapsible && leftCollapsed"
      class="collapse-toggle left-collapse-toggle collapsed"
      @click="toggleLeft"
      title="展开侧边栏"
    >
      <RightOutlined />
    </div>

    <!-- 左侧拖拽分隔条 -->
    <div
      v-show="!leftCollapsed"
      class="splitter splitter-left"
      @mousedown="startLeftResize"
      :class="{ resizing: isLeftResizing }"
    />

    <!-- 中间面板 -->
    <div class="pane pane-center">
      <slot name="center" />
    </div>

    <!-- 右侧拖拽分隔条 -->
    <div
      v-show="rightCollapsible ? !rightCollapsed : showRightPane"
      class="splitter splitter-right"
      @mousedown="startRightResize"
      :class="{ resizing: isRightResizing }"
    />

    <!-- 右侧面板 -->
    <div
      v-show="rightCollapsible ? !rightCollapsed : showRightPane"
      class="pane pane-right"
      :style="{ width: effectiveRightWidth + 'px' }"
    >
      <slot name="right" />
    </div>

    <!-- 右侧收起/展开细条入口（仅在收起后显示） -->
    <div
      v-if="rightCollapsible && rightCollapsed"
      class="collapse-toggle right-collapse-toggle collapsed"
      @click="toggleRight"
      title="展开侧边栏"
    >
      <LeftOutlined />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { LeftOutlined, RightOutlined } from '@ant-design/icons-vue'

/** 拖拽到此宽度以下自动收起面板 */
const DRAG_COLLAPSE_THRESHOLD = 30

/**
 * 三栏可调整面板组件 - 支持左右两侧面板拖拽调整宽度和收起/展开
 */
interface Props {
  /** 左侧面板最小宽度（拖拽不会低于此值，但可收起到0） */
  leftMin?: number
  /** 左侧面板最大宽度 */
  leftMax?: number
  /** 右侧面板最小宽度（拖拽不会低于此值，但可收起到0） */
  rightMin?: number
  /** 右侧面板最大宽度 */
  rightMax?: number
  /** 左侧面板初始宽度比例（相对于容器） */
  initialLeftRatio?: number
  /** 右侧面板初始宽度比例（相对于容器） */
  initialRightRatio?: number
  /** 左侧面板是否可收起 */
  leftCollapsible?: boolean
  /** 左侧面板是否已收起（v-model:leftCollapsed） */
  leftCollapsed?: boolean
  /** 右侧面板是否可收起 */
  rightCollapsible?: boolean
  /** 右侧面板是否已收起（v-model:rightCollapsed） */
  rightCollapsed?: boolean
  /** 是否显示右侧面板（仅在不可收起时生效） */
  showRightPane?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  leftMin: 200,
  leftMax: 1000,
  rightMin: 200,
  rightMax: 1000,
  initialLeftRatio: 0.25,
  initialRightRatio: 0.25,
  leftCollapsible: false,
  leftCollapsed: false,
  rightCollapsible: false,
  rightCollapsed: false,
  showRightPane: true
})

const emit = defineEmits<{
  resize: [leftSize: number, rightSize: number]
  'update:leftCollapsed': [value: boolean]
  'update:rightCollapsed': [value: boolean]
}>()

const containerRef = ref<HTMLElement | null>(null)
const leftSize = ref(300)
const rightSize = ref(380)
const previousLeftWidth = ref(300)
const previousRightWidth = ref(380)
const isLeftResizing = ref(false)
const isRightResizing = ref(false)

const effectiveLeftWidth = computed(() => props.leftCollapsed ? 0 : leftSize.value)
const effectiveRightWidth = computed(() => props.rightCollapsed ? 0 : rightSize.value)

/** 切换左侧面板收起/展开 */
const toggleLeft = () => {
  const next = !props.leftCollapsed
  if (next) {
    previousLeftWidth.value = leftSize.value
  } else {
    leftSize.value = Math.max(props.leftMin, Math.min(props.leftMax, previousLeftWidth.value))
  }
  emit('update:leftCollapsed', next)
}

/** 切换右侧面板收起/展开 */
const toggleRight = () => {
  const next = !props.rightCollapsed
  if (next) {
    previousRightWidth.value = rightSize.value
  } else {
    rightSize.value = Math.max(props.rightMin, Math.min(props.rightMax, previousRightWidth.value))
  }
  emit('update:rightCollapsed', next)
}

/** 同步外部 leftCollapsed 变化 */
watch(() => props.leftCollapsed, (collapsed) => {
  if (!collapsed && leftSize.value === 0) {
    leftSize.value = Math.max(props.leftMin, Math.min(props.leftMax, previousLeftWidth.value))
  }
})

/** 同步外部 rightCollapsed 变化 */
watch(() => props.rightCollapsed, (collapsed) => {
  if (!collapsed && rightSize.value === 0) {
    rightSize.value = Math.max(props.rightMin, Math.min(props.rightMax, previousRightWidth.value))
  }
})

/** 处理左侧拖拽调整 */
const onLeftResize = (e: MouseEvent) => {
  if (!containerRef.value) return

  const containerRect = containerRef.value.getBoundingClientRect()
  let newWidth = e.clientX - containerRect.left

  newWidth = Math.max(0, Math.min(props.leftMax, newWidth))
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

/** 停止左侧拖拽，低于阈值则自动收起 */
const stopLeftResize = () => {
  isLeftResizing.value = false
  document.removeEventListener('mousemove', onLeftResize)
  document.removeEventListener('mouseup', stopLeftResize)

  // 拖拽到阈值以下自动收起
  if (props.leftCollapsible && leftSize.value < DRAG_COLLAPSE_THRESHOLD) {
    previousLeftWidth.value = Math.max(props.leftMin, DRAG_COLLAPSE_THRESHOLD + 10)
    emit('update:leftCollapsed', true)
  }
}

/** 处理右侧拖拽调整 */
const onRightResize = (e: MouseEvent) => {
  if (!containerRef.value) return

  const containerRect = containerRef.value.getBoundingClientRect()
  let newWidth = containerRect.right - e.clientX

  newWidth = Math.max(0, Math.min(props.rightMax, newWidth))
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

/** 停止右侧拖拽，低于阈值则自动收起 */
const stopRightResize = () => {
  isRightResizing.value = false
  document.removeEventListener('mousemove', onRightResize)
  document.removeEventListener('mouseup', stopRightResize)

  // 拖拽到阈值以下自动收起
  if (props.rightCollapsible && rightSize.value < DRAG_COLLAPSE_THRESHOLD) {
    previousRightWidth.value = Math.max(props.rightMin, DRAG_COLLAPSE_THRESHOLD + 10)
    emit('update:rightCollapsed', true)
  }
}

/** 初始化面板尺寸 */
const initSizes = () => {
  if (!containerRef.value) return

  const containerWidth = containerRef.value.offsetWidth
  if (containerWidth === 0) return

  leftSize.value = Math.max(props.leftMin, Math.min(props.leftMax, containerWidth * props.initialLeftRatio))
  previousLeftWidth.value = leftSize.value

  if (props.showRightPane || props.rightCollapsible) {
    rightSize.value = Math.max(props.rightMin, Math.min(props.rightMax, containerWidth * props.initialRightRatio))
    previousRightWidth.value = rightSize.value
  }
}

// 暴露方法供父组件通过 ref 调用
defineExpose({
  toggleLeft,
  toggleRight
})

// ResizeObserver 实例
let resizeObserver: ResizeObserver | null = null

onMounted(() => {
  if (containerRef.value && typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        if (entry.contentRect.width > 0) {
          initSizes()
        }
      }
    })
    resizeObserver.observe(containerRef.value)
  } else {
    nextTick(() => {
      initSizes()
      setTimeout(initSizes, 100)
    })
  }

  window.addEventListener('resize', initSizes)
})

onUnmounted(() => {
  if (resizeObserver && containerRef.value) {
    resizeObserver.unobserve(containerRef.value)
    resizeObserver.disconnect()
  }
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
  transition: width 0.15s ease-out;
}

.pane-center {
  flex: 1;
  min-width: 0;
}

.splitter {
  width: 6px;
  background: rgba(0, 0, 0, 0.05);
  cursor: col-resize;
  flex-shrink: 0;
  transition: background 0.2s;
  position: relative;
  z-index: 10;

  &:hover,
  &.resizing {
    background: var(--primary-color);
  }

  &::before {
    content: '';
    position: absolute;
    left: 50%;
    top: 50%;
    transform: translate(-50%, -50%);
    width: 2px;
    height: 40px;
    background: rgba(0, 0, 0, 0.15);
    border-radius: 1px;
  }
}

.collapse-toggle {
  position: relative;
  z-index: 11;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  cursor: pointer;
  transition: all 0.2s ease;
  user-select: none;
  width: 20px;
  height: 100%;

  &:hover {
    color: var(--primary-color);
  }
}

.left-collapse-toggle {
  background: rgba(0, 0, 0, 0.03);
  color: var(--text-secondary);
  border-right: 1px solid var(--border-color);

  &:hover {
    background: rgba(0, 0, 0, 0.06);
    color: var(--primary-color);
  }

  &.collapsed {
    border-right: 1px solid var(--border-color);
    border-left: 1px solid var(--border-color);
    background: rgba(0, 0, 0, 0.03);

    &:hover {
      background: rgba(0, 0, 0, 0.08);
    }
  }
}

.right-collapse-toggle {
  background: rgba(0, 0, 0, 0.03);
  color: var(--text-secondary);
  border-left: 1px solid var(--border-color);

  &:hover {
    background: rgba(0, 0, 0, 0.06);
    color: var(--primary-color);
  }

  &.collapsed {
    border-left: 1px solid var(--border-color);
    border-right: 1px solid var(--border-color);
    background: rgba(0, 0, 0, 0.03);

    &:hover {
      background: rgba(0, 0, 0, 0.08);
    }
  }
}
</style>
