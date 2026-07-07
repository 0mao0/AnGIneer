<template>
  <!-- 三栏可调整面板组件 - 支持左右两侧面板宽度调整 -->
  <div class="split-pane" ref="containerRef" :class="{ 'left-collapsed': leftCollapsed }">
    <div class="pane pane-left" :style="{ width: effectiveLeftWidth + 'px' }" v-show="!leftCollapsed">
      <slot name="left" />
    </div>

    <div
      v-if="leftCollapsible"
      class="collapse-toggle left-collapse-toggle"
      :class="{ collapsed: leftCollapsed }"
      @click="toggleLeftCollapse"
      :title="leftCollapsed ? '展开侧边栏' : '收起侧边栏'"
    >
      <LeftOutlined v-if="!leftCollapsed" />
      <RightOutlined v-else />
    </div>

    <div
      v-show="!leftCollapsed"
      class="splitter splitter-left"
      @mousedown="startLeftResize"
      :class="{ resizing: isLeftResizing }"
    />

    <div class="pane pane-center">
      <slot name="center" />
    </div>

    <template v-if="showRightPane">
      <div class="splitter splitter-right" @mousedown="startRightResize" :class="{ resizing: isRightResizing }" />

      <div class="pane pane-right" :style="{ width: rightSize + 'px' }">
        <slot name="right" />
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { LeftOutlined, RightOutlined } from '@ant-design/icons-vue'

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
  /** 左侧面板是否可收起 */
  leftCollapsible?: boolean
  /** 左侧面板是否已收起（v-model） */
  leftCollapsed?: boolean
  /** 是否显示右侧面板 */
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
  showRightPane: true
})

const emit = defineEmits<{
  resize: [leftSize: number, rightSize: number]
  'update:leftCollapsed': [value: boolean]
}>()

const containerRef = ref<HTMLElement | null>(null)
const leftSize = ref(300)
const rightSize = ref(380)
const previousLeftWidth = ref(300)
const isLeftResizing = ref(false)
const isRightResizing = ref(false)

const effectiveLeftWidth = computed(() => props.leftCollapsed ? 0 : leftSize.value)

/** 切换左侧面板收起/展开 */
const toggleLeftCollapse = () => {
  const next = !props.leftCollapsed
  if (next) {
    // 收起：保存当前宽度
    previousLeftWidth.value = leftSize.value
  } else {
    // 展开：恢复之前宽度
    leftSize.value = Math.max(props.leftMin, Math.min(props.leftMax, previousLeftWidth.value))
  }
  emit('update:leftCollapsed', next)
}

/** 同步外部 leftCollapsed 变化 */
watch(() => props.leftCollapsed, (collapsed) => {
  if (!collapsed && leftSize.value === 0) {
    leftSize.value = Math.max(props.leftMin, Math.min(props.leftMax, previousLeftWidth.value))
  }
})

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
  // 计算右侧面板的新宽度：容器右边 - 鼠标位置
  let newWidth = containerRect.right - e.clientX

  // 限制在最小和最大宽度之间
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
  // 只有在获取到有效宽度时才初始化
  if (containerWidth === 0) return

  leftSize.value = Math.max(props.leftMin, Math.min(props.leftMax, containerWidth * props.initialLeftRatio))
  previousLeftWidth.value = leftSize.value

  if (props.showRightPane) {
    rightSize.value = Math.max(props.rightMin, Math.min(props.rightMax, containerWidth * props.initialRightRatio))
  }
}

// ResizeObserver 实例
let resizeObserver: ResizeObserver | null = null

onMounted(() => {
  // 使用 ResizeObserver 监听容器尺寸变化
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
    // 降级方案：使用 nextTick 和 setTimeout
    nextTick(() => {
      initSizes()
      // 延迟再次初始化，确保父容器布局完成
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
}

.left-collapse-toggle {
  width: 20px;
  height: 100%;
  background: rgba(0, 0, 0, 0.03);
  color: var(--text-secondary);
  border-right: 1px solid var(--border-color);

  &:hover {
    background: rgba(0, 0, 0, 0.06);
    color: var(--primary-color);
  }

  &.collapsed {
    width: 20px;
    border-right: 1px solid var(--border-color);
    border-left: 1px solid var(--border-color);
    background: rgba(0, 0, 0, 0.03);

    &:hover {
      background: rgba(0, 0, 0, 0.08);
    }
  }
}
</style>
