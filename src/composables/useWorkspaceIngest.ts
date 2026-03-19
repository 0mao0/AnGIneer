import { computed, ref, watch, type ComputedRef } from 'vue'
import type { KnowledgeTreeNode } from '../types/tree'
import type { IngestStatus, KnowledgeStrategy, StructuredStats } from '../types/knowledge'

interface UseWorkspaceIngestOptions {
  node: ComputedRef<KnowledgeTreeNode>
  content: ComputedRef<string>
  isContentDirty: ComputedRef<boolean>
  ingestStatus: ComputedRef<IngestStatus>
  ingestStage: ComputedRef<string>
  structuredStats: ComputedRef<StructuredStats | undefined>
}

export function useWorkspaceIngest(options: UseWorkspaceIngestOptions) {
  const ingestModalVisible = ref(false)
  const selectedStrategy = ref<KnowledgeStrategy>((options.node.value.strategy as KnowledgeStrategy) || 'A_structured')

  const ingestProgressStatus = computed(() => {
    if (options.ingestStatus.value === 'failed') return 'exception'
    if (options.ingestStatus.value === 'completed') return 'success'
    return 'active'
  })

  const ingestStageText = computed(() => {
    if (options.ingestStatus.value === 'failed') {
      return options.ingestStage.value || '入库失败'
    }
    if (options.ingestStatus.value === 'completed') {
      return options.ingestStage.value || '入库完成'
    }
    return options.ingestStage.value || '正在入库'
  })

  const strategyValue = computed(() => selectedStrategy.value)
  const structuredTotal = computed(() => Number(options.structuredStats.value?.total || 0))
  const hasParsedContent = computed(() => Boolean((options.content.value || '').trim()))
  const selectedStrategyStats = computed<Record<string, number>>(() => {
    const strategy = strategyValue.value
    return options.structuredStats.value?.strategies?.[strategy] || {}
  })
  const selectedStrategyTotal = computed(() => {
    const stats = selectedStrategyStats.value
    return Object.values(stats).reduce((sum, count) => sum + Number(count || 0), 0)
  })
  const indexSummaryStats = computed(() => {
    const stats = selectedStrategyStats.value
    const toCount = (value: unknown) => Number(value || 0)
    return {
      total: selectedStrategyTotal.value,
      formula: toCount(stats.formula),
      table: toCount(stats.table),
      figure: toCount(stats.image) + toCount(stats.figure)
    }
  })
  const ingestButtonText = computed(() => (selectedStrategyTotal.value > 0 ? '重新入库' : '入库'))
  const canIngest = computed(() => hasParsedContent.value && !options.isContentDirty.value)

  const onStrategyChange = (value: KnowledgeStrategy) => {
    selectedStrategy.value = value
  }

  const triggerIngest = () => {
    if (!canIngest.value) {
      return false
    }
    ingestModalVisible.value = true
    return true
  }

  const openIngestModal = () => {
    ingestModalVisible.value = true
  }

  const closeIngestModal = () => {
    ingestModalVisible.value = false
  }

  watch(() => options.node.value.key, () => {
    ingestModalVisible.value = false
    selectedStrategy.value = (options.node.value.strategy as KnowledgeStrategy) || 'A_structured'
  })

  watch(() => options.node.value.strategy, (value) => {
    selectedStrategy.value = (value as KnowledgeStrategy) || 'A_structured'
  }, { immediate: true })

  watch(options.ingestStatus, (value) => {
    if (value === 'processing') {
      ingestModalVisible.value = true
    }
  })

  return {
    ingestModalVisible,
    ingestProgressStatus,
    ingestStageText,
    strategyValue,
    structuredTotal,
    hasParsedContent,
    indexSummaryStats,
    ingestButtonText,
    canIngest,
    onStrategyChange,
    triggerIngest,
    openIngestModal,
    closeIngestModal
  }
}
