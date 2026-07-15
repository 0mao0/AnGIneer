<template>
  <div class="empty-state" :class="appClass">
    <div class="empty-icon">
      <component :is="resolvedIcon" v-if="resolvedIcon" />
    </div>
    <div class="empty-title">{{ title }}</div>
    <div v-if="description" class="empty-description">{{ description }}</div>
    <div v-if="$slots.action || ctaText" class="empty-action">
      <slot name="action">
        <a-button
          v-if="ctaText"
          :type="ctaType"
          @click="$emit('cta-click')"
        >
          {{ ctaText }}
        </a-button>
      </slot>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { InboxOutlined } from '@ant-design/icons-vue'
import { useTheme } from '../../composables/useTheme'

type EmptyVariant = 'empty' | 'error' | 'no-permission'

interface Props {
  title?: string
  description?: string
  variant?: EmptyVariant
  ctaText?: string
  ctaType?: 'default' | 'primary' | 'dashed' | 'link' | 'text'
  icon?: unknown
}

const props = withDefaults(defineProps<Props>(), {
  title: '暂无数据',
  description: '',
  variant: 'empty',
  ctaText: '',
  ctaType: 'primary',
  icon: undefined
})

defineEmits<{
  'cta-click': []
}>()

const { appClass } = useTheme()

const variantIconMap: Record<EmptyVariant, unknown> = {
  empty: InboxOutlined,
  error: () => '⚠',
  'no-permission': () => '🔒'
}

const resolvedIcon = computed(() => props.icon ?? variantIconMap[props.variant])
</script>

<style lang="less" scoped>
.empty-state {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 24px;
  text-align: center;
  gap: 12px;
}

.empty-icon {
  font-size: 48px;
  color: var(--text-secondary);
  opacity: 0.6;
}

.empty-title {
  font-size: 14px;
  color: var(--text-primary);
  font-weight: 500;
}

.empty-description {
  font-size: 12px;
  color: var(--text-secondary);
  max-width: 320px;
  line-height: 1.5;
}

.empty-action {
  margin-top: 8px;
}
</style>
