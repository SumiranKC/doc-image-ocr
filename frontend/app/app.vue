<!-- frontend/app.vue -->
<script setup lang="ts">
import { ref } from 'vue'
import { useSyncHighlight } from '../composables/useSyncHighlight'
import type { OcrExtractionResult } from '../types/ocr'

const { activeFieldKey, setActiveField } = useSyncHighlight()

const extractionData = ref<OcrExtractionResult>({
  imageUrl: 'https://placehold.co/600x800/png?text=Sample+ID+Document',
  documentType: 'Driver License',
  fields: {
    fullName: {
      key: 'fullName',
      label: 'Full Name',
      value: 'Jane Doe',
      confidence: 0.98,
      bbox: { x: 20, y: 15, width: 45, height: 6 }
    },
    dob: {
      key: 'dob',
      label: 'Date of Birth',
      value: '1995-06-01',
      confidence: 0.94,
      bbox: { x: 20, y: 24, width: 30, height: 5 }
    },
    docNumber: {
      key: 'docNumber',
      label: 'Document Number',
      value: 'DL-9082314A',
      confidence: 0.89,
      bbox: { x: 20, y: 32, width: 35, height: 5 }
    }
  }
})
</script>

<template>
  <div class="min-h-screen bg-slate-900 text-slate-100 flex flex-col font-sans">
    <header class="border-b border-slate-800 px-6 py-3 flex items-center justify-between">
      <div class="flex items-center gap-2">
        <span class="font-bold text-lg text-emerald-400">OCR Autofill Engine</span>
        <span class="text-xs bg-slate-800 px-2 py-0.5 rounded text-slate-400">Vue 3 / Nuxt</span>
      </div>
      <div class="text-xs text-slate-400">
        Active Focus: <span class="text-emerald-400 font-mono">{{ activeFieldKey || 'None' }}</span>
      </div>
    </header>

    <main class="flex-1 grid grid-cols-1 md:grid-cols-2 gap-6 p-6 overflow-hidden">
      <!-- Left: Document Preview -->
      <section class="bg-slate-800/60 rounded-xl p-4 border border-slate-700 flex flex-col">
        <h2 class="text-xs font-bold uppercase tracking-wider text-slate-400 mb-3">
          Document Preview
        </h2>
        <div class="flex-1 relative overflow-auto rounded-lg border border-slate-700 bg-slate-950 flex items-center justify-center p-4">
          <div class="relative inline-block max-w-full">
            <img 
              :src="extractionData.imageUrl" 
              alt="Uploaded document" 
              class="max-h-[68vh] rounded shadow-md object-contain select-none"
            />
            <div
              v-for="field in extractionData.fields"
              :key="field.key"
              v-show="field.bbox"
              :style="{
                left: `${field.bbox?.x}%`,
                top: `${field.bbox?.y}%`,
                width: `${field.bbox?.width}%`,
                height: `${field.bbox?.height}%`,
              }"
              :class="[
                'absolute border-2 rounded transition-all duration-150 cursor-pointer',
                activeFieldKey === field.key 
                  ? 'border-emerald-400 bg-emerald-400/20 shadow-lg' 
                  : 'border-slate-500/40 hover:border-slate-400'
              ]"
              @mouseenter="setActiveField(field.key)"
              @mouseleave="setActiveField(null)"
            />
          </div>
        </div>
      </section>

      <!-- Right: Form Autofill -->
      <section class="bg-slate-800/60 rounded-xl p-6 border border-slate-700 flex flex-col justify-between">
        <div>
          <div class="flex items-center justify-between mb-4">
            <h2 class="text-xs font-bold uppercase tracking-wider text-slate-400">
              Extracted Fields
            </h2>
            <span class="text-xs bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 px-2 py-0.5 rounded font-mono">
              {{ extractionData.documentType }}
            </span>
          </div>

          <div class="space-y-4">
            <div 
              v-for="(field, key) in extractionData.fields" 
              :key="key"
              :class="[
                'p-3 rounded-lg border transition-all duration-150',
                activeFieldKey === key 
                  ? 'border-emerald-500 bg-emerald-950/20' 
                  : 'border-slate-700 bg-slate-900/50'
              ]"
            >
              <div class="flex justify-between items-center mb-1">
                <label :for="key" class="text-xs font-medium text-slate-300">
                  {{ field.label }}
                </label>
                <span 
                  :class="[
                    'text-[10px] px-1.5 py-0.5 rounded font-mono',
                    field.confidence >= 0.9 ? 'text-emerald-400 bg-emerald-950' : 'text-amber-400 bg-amber-950'
                  ]"
                >
                  {{ Math.round(field.confidence * 100) }}% conf
                </span>
              </div>
              <input 
                :id="key"
                v-model="field.value"
                type="text"
                @focus="setActiveField(key)"
                @blur="setActiveField(null)"
                @mouseenter="setActiveField(key)"
                @mouseleave="setActiveField(null)"
                class="w-full bg-slate-950 border border-slate-700 rounded px-3 py-1.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-400"
              />
            </div>
          </div>
        </div>

        <button class="w-full mt-6 bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-semibold py-2.5 rounded-lg transition-colors">
          Confirm & Submit
        </button>
      </section>
    </main>
  </div>
</template>