import { ref, watch } from 'vue'

const STORAGE_PREFIX = 'angineer:sop-progress:'

function readProgress(sopId: string): number {
  if (!sopId) return 0
  const raw = localStorage.getItem(STORAGE_PREFIX + sopId)
  const n = Number(raw)
  return Number.isFinite(n) && n >= 0 ? n : 0
}

function writeProgress(sopId: string, step: number) {
  if (!sopId) return
  localStorage.setItem(STORAGE_PREFIX + sopId, String(step))
}

function clearProgress(sopId: string) {
  if (!sopId) return
  localStorage.removeItem(STORAGE_PREFIX + sopId)
}

export function useSopProgress(sopId: () => string) {
  const currentStep = ref(0)

  const applyStored = () => {
    currentStep.value = readProgress(sopId())
  }

  watch(sopId, applyStored, { immediate: true })

  watch(currentStep, (step) => {
    writeProgress(sopId(), step)
  })

  const markComplete = () => {
    clearProgress(sopId())
  }

  return { currentStep, markComplete }
}
