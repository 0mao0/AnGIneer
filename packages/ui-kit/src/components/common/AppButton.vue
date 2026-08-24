<template>
  <a-button
    v-bind="$attrs"
    class="app-btn"
    :class="[`app-btn--${variant}`]"
    :type="antType"
    :size="antSize"
    :danger="danger"
    :block="block"
    :loading="loading"
    :disabled="disabled"
    :html-type="htmlType"
  >
    <slot />
  </a-button>
</template>

<script setup lang="ts">
import { computed } from 'vue'

type AppButtonVariant = 'primary' | 'secondary' | 'danger' | 'text' | 'link' | 'dashed'
type AppButtonSize = 'sm' | 'md' | 'lg'

const props = withDefaults(defineProps<{
  /** 语义按钮类型：primary 主操作 / secondary 次要操作 / danger 危险操作 / text 文字 / link 链接 / dashed 虚线 */
  variant?: AppButtonVariant
  size?: AppButtonSize
  danger?: boolean
  block?: boolean
  loading?: boolean
  disabled?: boolean
  htmlType?: 'button' | 'submit' | 'reset'
}>(), {
  variant: 'secondary',
  size: 'md',
  danger: false,
  block: false,
  loading: false,
  disabled: false,
  htmlType: 'button',
})

const antType = computed(() => {
  switch (props.variant) {
    case 'primary': return 'primary'
    case 'text': return 'text'
    case 'link': return 'link'
    case 'dashed': return 'dashed'
    default: return 'default'
  }
})

const antSize = computed(() => {
  if (props.size === 'sm') return 'small'
  if (props.size === 'lg') return 'large'
  return undefined
})
</script>

<style scoped lang="less">
@import '../../styles/variables.less';

.app-btn {
  &--secondary {
    color: @brand-primary;
    border-color: @brand-primary;

    &:hover,
    &:focus {
      color: @brand-primary-hover;
      border-color: @brand-primary-hover;
    }
  }

  &--danger {
    color: @danger;
    border-color: @danger;
  }
}
</style>
