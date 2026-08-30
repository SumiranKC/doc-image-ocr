// frontend/composables/useSyncHighlight.ts
import { ref } from 'vue'

const activeFieldKey = ref<string | null>(null)

export const useSyncHighlight = () => {
  const setActiveField = (key: string | null) => {
    activeFieldKey.value = key
  }

  return {
    activeFieldKey,
    setActiveField
  }
}
