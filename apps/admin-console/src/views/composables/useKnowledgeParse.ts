import { ref, computed } from 'vue'
import { knowledgeApi, type KnowledgeParseOptions, type LlmConfigOption } from '@/api/knowledge'

type ParseSettingsState = {
  use_llm: boolean
  llm_model: string
}

const PARSE_SETTINGS_STORAGE_KEY = 'angineer-admin-knowledge-parse-settings-v1'
const DEFAULT_PARSE_LLM_MODEL = 'Qwen3.6-35B-A3B (Private)'

/** 从可用模型列表中选择解析默认模型 */
const pickDefaultLlmModel = (configs: LlmConfigOption[]): string => {
  const configuredConfigs = configs.filter(item => item.configured)
  const preferredModel = configuredConfigs.find(item => item.name === DEFAULT_PARSE_LLM_MODEL)
  return preferredModel?.name || configuredConfigs[0]?.name || ''
}

/** 管理文档解析流程：触发解析、轮询状态、解析设置 */
export function useKnowledgeParse() {
  const parsePollTimer = ref<number | null>(null)
  const parseSettingsVisible = ref(false)
  const llmConfigsLoading = ref(false)
  const llmConfigOptions = ref<LlmConfigOption[]>([])
  const parseSettings = ref<ParseSettingsState>({
    use_llm: true,
    llm_model: ''
  })

  const llmModelOptions = computed(() => llmConfigOptions.value.map(item => ({
    label: item.configured ? item.name : `${item.name}（未配置）`,
    value: item.name,
    disabled: !item.configured
  })))

  /** 归一化解析设置，兼容本地缓存与模型列表变化 */
  const normalizeParseSettings = (raw?: Partial<ParseSettingsState> | null): ParseSettingsState => {
    const useLlm = raw?.use_llm !== false
    if (!useLlm) {
      return { use_llm: false, llm_model: '' }
    }
    const configuredModelNames = new Set(
      llmConfigOptions.value.filter(item => item.configured).map(item => item.name)
    )
    const rawModel = typeof raw?.llm_model === 'string' ? raw.llm_model.trim() : ''
    return {
      use_llm: true,
      llm_model: rawModel && configuredModelNames.has(rawModel)
        ? rawModel
        : pickDefaultLlmModel(llmConfigOptions.value)
    }
  }

  /** 持久化解析设置 */
  const persistParseSettings = () => {
    localStorage.setItem(PARSE_SETTINGS_STORAGE_KEY, JSON.stringify(parseSettings.value))
  }

  /** 读取本地缓存中的解析设置 */
  const loadStoredParseSettings = () => {
    try {
      const raw = localStorage.getItem(PARSE_SETTINGS_STORAGE_KEY)
      parseSettings.value = raw ? normalizeParseSettings(JSON.parse(raw)) : normalizeParseSettings()
    } catch {
      parseSettings.value = normalizeParseSettings()
    }
  }

  /** 拉取可用 LLM 模型列表 */
  const fetchLlmConfigs = async () => {
    llmConfigsLoading.value = true
    try {
      const result = await knowledgeApi.getLlmConfigs()
      llmConfigOptions.value = Array.isArray(result) ? result : []
    } catch {
      llmConfigOptions.value = []
    } finally {
      llmConfigsLoading.value = false
      parseSettings.value = normalizeParseSettings(parseSettings.value)
      persistParseSettings()
    }
  }

  /** 生成解析接口需要的参数载荷 */
  const buildParseOptionsPayload = (): KnowledgeParseOptions => {
    parseSettings.value = normalizeParseSettings(parseSettings.value)
    persistParseSettings()
    if (!parseSettings.value.use_llm) {
      return { use_llm: false }
    }
    return {
      use_llm: true,
      llm_model: parseSettings.value.llm_model || undefined
    }
  }

  /** 打开解析设置弹窗 */
  const showParseSettingsModal = async () => {
    parseSettingsVisible.value = true
    if (!llmConfigOptions.value.length) {
      await fetchLlmConfigs()
    }
  }

  /** 确认解析设置 */
  const handleParseSettingsConfirm = () => {
    parseSettings.value = normalizeParseSettings(parseSettings.value)
    persistParseSettings()
    parseSettingsVisible.value = false
  }

  /** 切换是否启用 LLM */
  const handleParseUseLlmChange = (checked: boolean) => {
    parseSettings.value = normalizeParseSettings({
      ...parseSettings.value,
      use_llm: checked
    })
  }

  /** 更新解析使用的模型配置名 */
  const handleParseModelChange = (value: string | undefined) => {
    parseSettings.value = normalizeParseSettings({
      ...parseSettings.value,
      llm_model: value || ''
    })
  }

  /** 停止解析轮询 */
  const stopParsePolling = () => {
    if (parsePollTimer.value) {
      window.clearInterval(parsePollTimer.value)
      parsePollTimer.value = null
    }
  }

  /** 启动解析轮询 */
  const startParsePolling = (
    taskId: string,
    docId: string,
    selectedNode: any,
    onLoadNodes: (key?: string) => Promise<void>,
    onLoadDocContent: (docId: string) => Promise<void>,
    onLoadStructuredStats: (docId: string) => Promise<void>
  ) => {
    stopParsePolling()
    parsePollTimer.value = window.setInterval(async () => {
      try {
        const task = await knowledgeApi.getParseTask(taskId) as any
        if (selectedNode && selectedNode.key === docId) {
          selectedNode.parseProgress = task.progress || 0
          selectedNode.parseStage = task.stage || ''
          selectedNode.parseError = task.error || ''
          selectedNode.status = task.status === 'completed'
            ? 'completed'
            : task.status === 'failed'
              ? 'failed'
              : 'processing'
        }
        if (task.status === 'completed' || task.status === 'failed') {
          stopParsePolling()
          await onLoadNodes(docId)
          if (task.status === 'completed') {
            await onLoadDocContent(docId)
            await onLoadStructuredStats(docId)
          }
        }
      } catch {
        stopParsePolling()
      }
    }, 1500)
  }

  return {
    parsePollTimer,
    parseSettingsVisible,
    llmConfigsLoading,
    llmConfigOptions,
    parseSettings,
    llmModelOptions,
    normalizeParseSettings,
    loadStoredParseSettings,
    fetchLlmConfigs,
    buildParseOptionsPayload,
    showParseSettingsModal,
    handleParseSettingsConfirm,
    handleParseUseLlmChange,
    handleParseModelChange,
    stopParsePolling,
    startParsePolling
  }
}
