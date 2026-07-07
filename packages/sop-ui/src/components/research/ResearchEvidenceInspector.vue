<template>
  <div class="research-evidence-inspector">
    <div v-if="sectionPath" class="inspector-section">
      <h5>章节路径</h5>
      <a-breadcrumb class="section-breadcrumb">
        <a-breadcrumb-item v-for="(seg, idx) in pathSegments" :key="idx">
          {{ seg }}
        </a-breadcrumb-item>
      </a-breadcrumb>
    </div>

    <div v-if="evidenceBlockIds.length" class="inspector-section">
      <h5>证据块（{{ evidenceBlockIds.length }}）</h5>
      <div class="evidence-tags">
        <a-tag
          v-for="blockId in evidenceBlockIds"
          :key="blockId"
          color="blue"
          class="evidence-tag"
          @click="emit('open-citation', blockId)"
        >
          {{ blockId.slice(0, 12) }}...
        </a-tag>
      </div>
    </div>

    <div v-if="citations.length" class="inspector-section">
      <h5>引用（{{ citations.length }}）</h5>
      <div v-for="(cit, idx) in citations" :key="idx" class="citation-item">
        <a-tag color="purple">{{ cit.title || cit.source || `引用 ${idx + 1}` }}</a-tag>
        <div v-if="cit.content" class="citation-content">{{ cit.content }}</div>
      </div>
    </div>

    <div v-if="!sectionPath && !evidenceBlockIds.length && !citations.length" class="inspector-empty">
      <div class="inspector-empty-icon"><SearchOutlined /></div>
      <span>选择查看证据</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { SearchOutlined } from '@ant-design/icons-vue'

interface Props {
  evidenceBlockIds: string[]
  sectionPath: string
  citations: any[]
}

const props = defineProps<Props>()

const emit = defineEmits<{
  'open-citation': [blockId: string]
}>()

const pathSegments = computed(() => {
  if (!props.sectionPath) return []
  return props.sectionPath.split(/[/.>]/).filter(Boolean)
})
</script>

<style lang="less" scoped>
.research-evidence-inspector {
  height: 100%;
  overflow-y: auto;
  padding: 16px;
}

.inspector-section {
  margin-bottom: 16px;

  h5 {
    margin: 0 0 8px;
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary);
  }
}

.section-breadcrumb {
  font-size: 12px;
}

.evidence-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;

  .evidence-tag {
    cursor: pointer;
    transition: opacity 0.2s;

    &:hover {
      opacity: 0.8;
    }
  }
}

.citation-item {
  margin-bottom: 8px;

  .citation-content {
    font-size: 12px;
    color: var(--text-secondary);
    margin-top: 4px;
    line-height: 1.5;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
}

.inspector-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--text-secondary);
  gap: 8px;

  .inspector-empty-icon {
    font-size: 36px;
    opacity: 0.3;
  }
}
</style>
