<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  createSavedForm, deleteSavedForm, extractDocument, getMediaPage, getOriginalMedia,
  getSavedForm, heartbeat, initializeSession, listSavedForms, saveUploadedMedia, updateSavedForm,
  type ExtractionResponse, type FieldValue, type FormType, type MediaItem,
  type SavedForm, type SavedFormSummary, type UploadMode,
} from './api'

type Definition = { key: string; label: string; long?: boolean }
type ReviewMedia = MediaItem & { draft?: boolean }
const maxSavedForms = 5
const templates: Record<FormType, { name: string; description: string; fields: Definition[] }> = {
  person: {
    name: 'Contact Person', description: 'Capture an individual’s details from an image or PDF.',
    fields: [
      { key: 'full_name', label: 'Full name' }, { key: 'title', label: 'Title' },
      { key: 'job_title', label: 'Job title' }, { key: 'organization', label: 'Organization' },
      { key: 'email', label: 'Email' }, { key: 'phone', label: 'Phone' },
      { key: 'website', label: 'Website' }, { key: 'address', label: 'Address', long: true },
      { key: 'notes', label: 'Notes', long: true },
    ],
  },
  organization: {
    name: 'Organization', description: 'Capture a company or group’s contact details.',
    fields: [
      { key: 'organization_name', label: 'Organization name' },
      { key: 'email', label: 'Email' }, { key: 'phone', label: 'Phone' },
      { key: 'website', label: 'Website' }, { key: 'address', label: 'Address', long: true },
      { key: 'description', label: 'Description', long: true },
    ],
  },
}
const screen = ref<'new' | 'saved' | 'detail'>('new')
const pickedType = ref<FormType | null>(null)
const savedForms = ref<SavedFormSummary[]>([])
const selectedForm = ref<SavedForm | null>(null)
const fields = ref<Record<string, FieldValue>>({})
const mode = ref<'create' | UploadMode | null>(null)
const editing = ref(false)
const draft = ref<ExtractionResponse | null>(null)
const draftFile = ref<File | null>(null)
const draftUrl = ref<string | null>(null)
const savedMediaUrl = ref<string | null>(null)
const mediaId = ref<string | null>(null)
const pageIndex = ref(0)
const activeField = ref<string | null>(null)
const busy = ref(false)
const busyLabel = ref('')
const error = ref('')
const notice = ref('')

const template = computed(() => pickedType.value ? templates[pickedType.value] : null)
const formLimitReached = computed(() => savedForms.value.length >= maxSavedForms)
const media = computed<ReviewMedia[]>(() => {
  const existing = mode.value === 'replace' ? [] : (selectedForm.value?.media ?? [])
  if (!draft.value || !draftFile.value) return existing
  return [...existing, {
    id: draft.value.document_id, filename: draftFile.value.name,
    mime_type: draftFile.value.type, page_count: draft.value.pages.length,
    pages: draft.value.pages, text_blocks: draft.value.text_blocks, draft: true,
  }]
})
const currentMedia = computed(() => media.value.find(item => item.id === mediaId.value) ?? media.value[0] ?? null)
const currentPage = computed(() => currentMedia.value?.pages[pageIndex.value] ?? null)
const imageUrl = computed(() => {
  const item = currentMedia.value
  if (!item) return ''
  if (item.draft) return item.pages[pageIndex.value]?.data_url ?? draftUrl.value ?? ''
  return savedMediaUrl.value ?? ''
})
const marks = computed(() => {
  const item = currentMedia.value
  if (!item || !template.value) return []
  return template.value.fields.flatMap(definition => {
    const field = fields.value[definition.key]
    if (!field?.value.trim() || field.source_media_id !== item.id || field.source_block_index == null) return []
    const block = item.text_blocks[field.source_block_index]
    return block && block.page_index === pageIndex.value
      ? [{ key: definition.key, block, active: activeField.value === definition.key }]
      : []
  })
})

function empty(): FieldValue {
  return { value: '', confidence: null, source_media_id: null, source_block_index: null, edited: false }
}
function blank(type: FormType): Record<string, FieldValue> {
  return Object.fromEntries(templates[type].fields.map(item => [item.key, empty()]))
}
function copy(source: Record<string, FieldValue>): Record<string, FieldValue> {
  return Object.fromEntries(Object.entries(source).map(([key, value]) => [key, { ...value }]))
}
function clearDraft() {
  if (draftUrl.value) URL.revokeObjectURL(draftUrl.value)
  draftUrl.value = null
  draft.value = null
  draftFile.value = null
  activeField.value = null
}
function clearSavedMediaUrl() {
  if (savedMediaUrl.value) URL.revokeObjectURL(savedMediaUrl.value)
  savedMediaUrl.value = null
}
function choose(type: FormType) {
  clearDraft()
  pickedType.value = type
  fields.value = blank(type)
  mode.value = 'create'
  error.value = ''
  notice.value = ''
}
function goNew() {
  history.pushState(null, '', '/')
  screen.value = 'new'
  selectedForm.value = null
  pickedType.value = null
  mode.value = null
  editing.value = false
  clearDraft()
  error.value = ''
  notice.value = ''
}
async function goSaved() {
  history.pushState(null, '', '/saved')
  screen.value = 'saved'
  selectedForm.value = null
  clearDraft()
  error.value = ''
  try { savedForms.value = await listSavedForms() }
  catch (caught) { error.value = getError(caught) }
}
function showRecord(record: SavedForm, updateUrl = true) {
  clearDraft()
  selectedForm.value = record
  pickedType.value = record.form_type
  fields.value = copy(record.fields)
  mediaId.value = record.media[0]?.id ?? null
  pageIndex.value = 0
  editing.value = false
  mode.value = null
  screen.value = 'detail'
  if (updateUrl) history.pushState(null, '', `/saved/${record.id}`)
}
async function openRecord(id: string) {
  try { showRecord(await getSavedForm(id)); error.value = ''; notice.value = '' }
  catch (caught) { error.value = getError(caught) }
}
async function syncRoute() {
  const match = location.pathname.match(/^\/saved\/([^/]+)$/)
  if (match) {
    try { showRecord(await getSavedForm(match[1]), false) }
    catch (caught) { screen.value = 'saved'; error.value = getError(caught) }
  } else if (location.pathname === '/saved') {
    screen.value = 'saved'
    try { savedForms.value = await listSavedForms() }
    catch (caught) { error.value = getError(caught) }
  } else { screen.value = 'new' }
}
let heartbeatTimer: number | undefined
let mediaRequestVersion = 0
watch(
  [() => selectedForm.value?.id, () => currentMedia.value?.id, pageIndex],
  async () => {
    const version = ++mediaRequestVersion
    clearSavedMediaUrl()
    const form = selectedForm.value
    const item = currentMedia.value
    if (!form || !item || item.draft) return
    try {
      const blob = await getMediaPage(form.id, item.id, pageIndex.value)
      if (version !== mediaRequestVersion) return
      savedMediaUrl.value = URL.createObjectURL(blob)
    } catch (caught) {
      if (version === mediaRequestVersion) error.value = getError(caught)
    }
  },
  { immediate: true },
)
onMounted(async () => {
  window.addEventListener('popstate', syncRoute)
  try {
    await initializeSession()
    await syncRoute()
    heartbeatTimer = window.setInterval(() => {
      void heartbeat().catch(caught => { error.value = getError(caught) })
    }, 60_000)
  } catch (caught) { error.value = getError(caught) }
})
onBeforeUnmount(() => {
  window.removeEventListener('popstate', syncRoute)
  if (heartbeatTimer !== undefined) window.clearInterval(heartbeatTimer)
  mediaRequestVersion++
  clearSavedMediaUrl()
  clearDraft()
})
function getError(caught: unknown): string {
  return caught instanceof Error ? caught.message : 'Something went wrong. Please try again.'
}
function startUpload(nextMode: UploadMode) {
  if (!selectedForm.value || (nextMode === 'add' && selectedForm.value.media.length >= 3)) return
  clearDraft()
  mode.value = nextMode
  editing.value = false
  fields.value = copy(selectedForm.value.fields)
  error.value = ''
  notice.value = ''
}
function cancelUpload() {
  clearDraft()
  if (selectedForm.value) {
    fields.value = copy(selectedForm.value.fields)
    mode.value = null
    mediaId.value = selectedForm.value.media[0]?.id ?? null
    pageIndex.value = 0
  } else if (pickedType.value) { fields.value = blank(pickedType.value) }
  error.value = ''
}
async function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file || !pickedType.value) return
  if (!['image/png', 'image/jpeg', 'image/webp', 'application/pdf'].includes(file.type)) {
    error.value = 'Choose a PNG, JPEG, WebP, or PDF file.'; return
  }
  if (file.size > 10 * 1024 * 1024) { error.value = 'The document must be 10 MB or smaller.'; return }
  error.value = ''
  notice.value = ''
  busy.value = true
  busyLabel.value = 'Reading and extracting the document…'
  try {
    const result = await extractDocument(file, pickedType.value)
    clearDraft()
    draft.value = result
    draftFile.value = file
    if (file.type !== 'application/pdf') draftUrl.value = URL.createObjectURL(file)
    fields.value = mode.value === 'add' && selectedForm.value ? copy(selectedForm.value.fields) : blank(pickedType.value)
    for (const suggestion of result.fields) {
      if (mode.value === 'add' && fields.value[suggestion.key]?.value.trim()) continue
      fields.value[suggestion.key] = {
        value: suggestion.value, confidence: suggestion.confidence,
        source_media_id: suggestion.source_media_id,
        source_block_index: suggestion.source_block_index, edited: false,
      }
    }
    mediaId.value = result.document_id
    pageIndex.value = 0
    if (!result.fields.length) notice.value = 'No matching fields were found. You can fill the form manually.'
  } catch (caught) { error.value = getError(caught) }
  finally { busy.value = false }
}
function locked(key: string): boolean {
  return mode.value === 'add' && Boolean(selectedForm.value?.fields[key]?.value.trim())
}
function editable(key: string): boolean { return Boolean((draft.value || editing.value) && !locked(key)) }
function updateValue(key: string, event: Event) {
  if (!editable(key)) return
  const value = (event.target as HTMLInputElement | HTMLTextAreaElement).value
  fields.value[key] = value.trim()
    ? { ...(fields.value[key] ?? empty()), value, edited: true }
    : { ...empty(), edited: true }
}
function focusField(key: string) {
  activeField.value = key
  const field = fields.value[key]
  if (!field?.source_media_id || field.source_block_index == null) return
  const item = media.value.find(candidate => candidate.id === field.source_media_id)
  const block = item?.text_blocks[field.source_block_index]
  if (item && block) { mediaId.value = item.id; pageIndex.value = block.page_index }
}
function selectMedia(id: string) { mediaId.value = id; pageIndex.value = 0; activeField.value = null }
function points(box: { x: number; y: number }[]): string {
  return box.map(point => `${point.x},${point.y}`).join(' ')
}
async function openOriginal() {
  if (!selectedForm.value || !currentMedia.value || currentMedia.value.draft) return
  const formId = selectedForm.value.id
  const currentMediaId = currentMedia.value.id
  const target = window.open('about:blank', '_blank')
  if (target) {
    target.opener = null
    target.document.title = 'Loading document…'
    target.document.body.textContent = 'Loading document…'
  }
  try {
    const blob = await getOriginalMedia(formId, currentMediaId)
    const url = URL.createObjectURL(blob)
    if (target) target.location.href = url
    else {
      const link = document.createElement('a')
      link.href = url
      link.target = '_blank'
      link.rel = 'noopener'
      link.click()
    }
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
  } catch (caught) {
    target?.close()
    error.value = getError(caught)
  }
}
async function saveDraft() {
  if (!draft.value || !draftFile.value || !pickedType.value || !mode.value) return
  busy.value = true
  busyLabel.value = 'Saving the form and document…'
  error.value = ''
  try {
    const record = mode.value === 'create'
      ? await createSavedForm(pickedType.value, draftFile.value, draft.value, fields.value)
      : await saveUploadedMedia(selectedForm.value!.id, mode.value, draftFile.value, draft.value, fields.value)
    showRecord(record)
    notice.value = 'Form and document saved.'
  } catch (caught) { error.value = getError(caught) }
  finally { busy.value = false }
}
async function saveEdits() {
  if (!selectedForm.value) return
  busy.value = true
  busyLabel.value = 'Saving your changes…'
  error.value = ''
  try { showRecord(await updateSavedForm(selectedForm.value.id, fields.value)); notice.value = 'Changes saved.' }
  catch (caught) { error.value = getError(caught) }
  finally { busy.value = false }
}
async function removeRecord() {
  if (!selectedForm.value || !confirm('Delete this form and all its documents? This cannot be undone.')) return
  busy.value = true
  busyLabel.value = 'Deleting the form and documents…'
  error.value = ''
  try { await deleteSavedForm(selectedForm.value.id); await goSaved(); notice.value = 'Form deleted.' }
  catch (caught) { error.value = getError(caught) }
  finally { busy.value = false }
}
function formatDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'short', year: 'numeric' }).format(new Date(value))
}
</script>

<template>
  <div :inert="busy" class="min-h-screen">
    <header class="border-b border-slate-200 bg-white">
      <div class="mx-auto flex max-w-7xl items-center justify-between gap-4 px-5 py-4 sm:px-8">
        <button class="flex items-center gap-3 text-left" @click="goNew"><span class="grid h-9 w-9 place-items-center rounded-xl bg-indigo-600 text-lg font-bold text-white">D</span><span class="text-lg font-bold tracking-tight text-slate-900">Document Forms</span></button>
        <nav class="flex items-center gap-1 rounded-xl bg-slate-100 p-1 text-sm font-medium" aria-label="Main navigation">
          <button class="rounded-lg px-3 py-2 transition" :class="screen === 'new' ? 'bg-white text-indigo-700 shadow-sm' : 'text-slate-600 hover:text-slate-900'" @click="goNew">New form</button>
          <button class="rounded-lg px-3 py-2 transition" :class="screen !== 'new' ? 'bg-white text-indigo-700 shadow-sm' : 'text-slate-600 hover:text-slate-900'" @click="goSaved">Saved forms</button>
        </nav>
      </div>
    </header>
    <main class="mx-auto max-w-7xl px-5 pb-20 pt-10 sm:px-8">
      <div role="note" class="mb-6 rounded-xl border border-indigo-200 bg-indigo-50 px-4 py-3 text-sm text-indigo-900">Temporary session: saved forms and documents are available only in this browser tab and are automatically removed about one hour after activity stops. Each session can hold up to 5 saved forms and 40 MB of documents.</div>
      <div v-if="error" role="alert" class="mb-6 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">{{ error }}</div>
      <div v-if="notice" role="status" class="mb-6 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{{ notice }}</div>

      <template v-if="screen === 'new' && !pickedType">
        <div class="max-w-2xl"><p class="eyebrow">Start here</p><h1 class="mt-3 text-4xl font-bold tracking-tight text-slate-950 sm:text-5xl">Choose the form you want to fill.</h1><p class="mt-4 text-lg leading-relaxed text-slate-600">Pick a form first. Then upload an image or PDF to turn its details into editable suggestions.</p></div>
        <div class="mt-10 grid gap-5 md:grid-cols-2">
          <button v-for="(choice, type) in templates" :key="type" class="group rounded-2xl border border-slate-200 bg-white p-7 text-left shadow-sm transition hover:-translate-y-1 hover:border-indigo-300 hover:shadow-lg" @click="choose(type)"><span class="grid h-12 w-12 place-items-center rounded-xl bg-indigo-50 text-xl text-indigo-700">{{ type === 'person' ? '◉' : '▦' }}</span><span class="mt-6 block text-2xl font-semibold text-slate-900">{{ choice.name }}</span><span class="mt-2 block max-w-sm text-sm leading-relaxed text-slate-600">{{ choice.description }}</span><span class="mt-6 inline-flex items-center gap-2 text-sm font-semibold text-indigo-700">Select form <span aria-hidden="true">→</span></span></button>
        </div>
      </template>

      <template v-else-if="screen === 'saved'">
        <div class="flex flex-wrap items-end justify-between gap-4"><div><p class="eyebrow">Your records</p><h1 class="mt-2 text-4xl font-bold tracking-tight text-slate-950">Saved forms</h1><p class="mt-3 text-slate-600">Open a form to review its documents, make changes, or upload more. {{ savedForms.length }} / {{ maxSavedForms }} form slots used.</p></div><button class="primary-button" :disabled="formLimitReached" @click="goNew">+ New form</button></div>
        <div v-if="!savedForms.length" class="mt-10 rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-16 text-center"><p class="text-xl font-semibold text-slate-800">No forms saved yet</p><p class="mt-2 text-sm text-slate-500">Choose a form and upload a document to create your first record.</p><button class="primary-button mt-6" @click="goNew">Create a form</button></div>
        <div v-else class="mt-8 grid gap-4 md:grid-cols-2 xl:grid-cols-3"><button v-for="record in savedForms" :key="record.id" class="rounded-2xl border border-slate-200 bg-white p-6 text-left shadow-sm transition hover:border-indigo-300 hover:shadow-md" @click="openRecord(record.id)"><span class="text-xs font-bold uppercase tracking-widest text-indigo-600">{{ templates[record.form_type].name }}</span><span class="mt-3 block truncate text-xl font-semibold text-slate-900">{{ record.display_name }}</span><span class="mt-5 flex items-center justify-between text-sm text-slate-500"><span>{{ record.media_count }} {{ record.media_count === 1 ? 'document' : 'documents' }}</span><span>{{ formatDate(record.updated_at) }}</span></span></button></div>
      </template>

      <template v-else>
        <div class="flex flex-wrap items-start justify-between gap-4"><div><button class="mb-3 text-sm font-semibold text-indigo-700 hover:underline" @click="screen === 'detail' ? goSaved() : goNew()">← {{ screen === 'detail' ? 'Saved forms' : 'Choose another form' }}</button><p class="eyebrow">{{ screen === 'detail' ? 'Saved record' : 'New record' }}</p><h1 class="mt-2 text-3xl font-bold tracking-tight text-slate-950 sm:text-4xl">{{ template?.name }}</h1><p class="mt-2 text-slate-600">{{ template?.description }}</p></div><span v-if="selectedForm" class="rounded-full bg-white px-3 py-1.5 text-sm font-medium text-slate-600 shadow-sm">{{ selectedForm.media.length }} / 3 documents</span></div>
        <div v-if="screen === 'detail' && !mode && !editing" class="mt-7 flex flex-wrap gap-3"><button class="primary-button" @click="editing = true">Edit details</button><button class="secondary-button" @click="startUpload('replace')">Replace with new document</button><button class="secondary-button" :disabled="(selectedForm?.media.length ?? 0) >= 3" @click="startUpload('add')">Add document</button><button class="danger-button" @click="removeRecord">Delete form</button><p v-if="(selectedForm?.media.length ?? 0) >= 3" class="w-full text-xs text-slate-500">Three-document limit reached. Replace the record to use a different document.</p></div>

        <div v-if="mode && !draft" class="mt-8 max-w-2xl rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8"><div class="flex items-start justify-between gap-4"><div><h2 class="text-xl font-semibold text-slate-900">{{ mode === 'replace' ? 'Replace the document and all data' : mode === 'add' ? 'Add to empty fields' : 'Upload a document' }}</h2><p class="mt-2 text-sm leading-relaxed text-slate-600">{{ mode === 'replace' ? 'The existing details and documents will be replaced when you save.' : mode === 'add' ? 'Existing filled fields stay intact. This document can fill empty fields.' : 'Upload an image or PDF to start filling this form.' }}</p></div><button v-if="screen === 'detail'" class="text-sm font-medium text-slate-500 hover:text-slate-900" @click="cancelUpload">Cancel</button></div><label class="mt-6 flex cursor-pointer flex-col items-center rounded-xl border-2 border-dashed border-indigo-200 bg-indigo-50/50 px-5 py-10 text-center hover:border-indigo-400 hover:bg-indigo-50"><span class="text-3xl text-indigo-600">↑</span><span class="mt-3 font-semibold text-indigo-800">Choose a document</span><span class="mt-1 text-sm text-slate-500">PNG, JPEG, WebP, or PDF · up to 10 MB · PDFs up to 10 pages</span><input class="sr-only" type="file" accept="image/png,image/jpeg,image/webp,application/pdf" @change="onFileChange"></label></div>

        <div v-if="draft || selectedForm" class="mt-8 grid items-start gap-6 lg:grid-cols-[minmax(0,1.1fr)_minmax(340px,0.9fr)]">
          <section class="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm" aria-label="Document preview"><div class="border-b border-slate-100 px-5 py-4"><div class="flex flex-wrap items-center justify-between gap-2"><h2 class="text-lg font-semibold text-slate-900">Source document</h2><button v-if="selectedForm && currentMedia && !currentMedia.draft" class="text-sm font-medium text-indigo-700 hover:underline" @click="openOriginal">Open original ↗</button></div><div v-if="media.length > 1" class="mt-4 flex flex-wrap gap-2" aria-label="Choose document"><button v-for="item in media" :key="item.id" class="max-w-52 truncate rounded-lg px-3 py-1.5 text-xs font-medium" :class="currentMedia?.id === item.id ? 'bg-indigo-600 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'" :title="item.filename" @click="selectMedia(item.id)">{{ item.filename }}</button></div><p v-if="currentMedia" class="mt-2 truncate text-xs text-slate-500">{{ currentMedia.filename }} <span v-if="currentMedia.mime_type === 'application/pdf'">· PDF preview</span></p></div><div v-if="currentMedia && currentPage" class="bg-slate-100 p-3 sm:p-5"><div class="relative mx-auto max-w-full overflow-hidden rounded-lg bg-white shadow" :style="{ aspectRatio: `${currentPage.width} / ${currentPage.height}` }"><img :src="imageUrl" :alt="`Page ${pageIndex + 1} of ${currentMedia.filename}`" class="block h-full w-full object-contain"><svg class="pointer-events-none absolute inset-0 h-full w-full" :viewBox="`0 0 ${currentPage.width} ${currentPage.height}`" preserveAspectRatio="none" aria-hidden="true"><polygon v-for="mark in marks" :key="mark.key" :points="points(mark.block.bounding_box)" :fill="mark.active ? '#f59e0b66' : '#6366f133'" :stroke="mark.active ? '#d97706' : '#4f46e5'" :stroke-width="mark.active ? 4 : 2" /></svg></div><div v-if="currentMedia.page_count > 1" class="mt-4 flex items-center justify-center gap-4 text-sm"><button class="secondary-button !px-3 !py-1.5" :disabled="pageIndex === 0" @click="pageIndex--">Previous</button><span class="font-medium text-slate-600">Page {{ pageIndex + 1 }} of {{ currentMedia.page_count }}</span><button class="secondary-button !px-3 !py-1.5" :disabled="pageIndex >= currentMedia.page_count - 1" @click="pageIndex++">Next</button></div></div></section>

          <section class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-7" aria-label="Form fields"><div class="flex flex-wrap items-start justify-between gap-3"><div><h2 class="text-lg font-semibold text-slate-900">{{ editing ? 'Edit details' : draft ? 'Review suggested details' : 'Form details' }}</h2><p class="mt-1 text-sm text-slate-500">{{ draft ? 'Highlighted fields came from the document. Select one to locate its source.' : 'Select a highlighted field to see where it came from.' }}</p></div><button v-if="editing" class="text-sm font-medium text-slate-500 hover:text-slate-900" @click="fields = copy(selectedForm!.fields); editing = false">Cancel</button></div><div class="mt-6 grid gap-5 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2"><div v-for="definition in template?.fields" :key="definition.key" :class="definition.long ? 'sm:col-span-2 lg:col-span-1 xl:col-span-2' : ''" @click="focusField(definition.key)"><div class="mb-1.5 flex flex-wrap items-center gap-2"><label class="text-sm font-semibold text-slate-700" :for="`field-${definition.key}`">{{ definition.label }}</label><span v-if="fields[definition.key]?.source_media_id && fields[definition.key]?.value" class="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide" :class="fields[definition.key]?.edited ? 'bg-amber-100 text-amber-800' : 'bg-indigo-100 text-indigo-700'">{{ fields[definition.key]?.edited ? 'Corrected' : 'From document' }}</span></div><textarea v-if="definition.long" :id="`field-${definition.key}`" :value="fields[definition.key]?.value ?? ''" rows="3" class="field-input resize-y" :class="fields[definition.key]?.source_media_id ? 'border-indigo-300 bg-indigo-50/40' : ''" :readonly="!editable(definition.key)" @input="updateValue(definition.key, $event)" @focus="focusField(definition.key)" /><input v-else :id="`field-${definition.key}`" :value="fields[definition.key]?.value ?? ''" class="field-input" :class="fields[definition.key]?.source_media_id ? 'border-indigo-300 bg-indigo-50/40' : ''" type="text" :readonly="!editable(definition.key)" @input="updateValue(definition.key, $event)" @focus="focusField(definition.key)"><p v-if="locked(definition.key)" class="mt-1 text-xs text-slate-500">Kept from the existing form</p></div></div><div v-if="draft || editing" class="mt-8 flex flex-wrap gap-3 border-t border-slate-100 pt-6"><button class="primary-button" @click="draft ? saveDraft() : saveEdits()">{{ draft ? 'Finish and save' : 'Save changes' }}</button><button v-if="draft" class="secondary-button" @click="cancelUpload">Cancel upload</button></div></section>
        </div>
      </template>
    </main>
  </div>
  <div v-if="busy" class="fixed inset-0 z-50 grid place-items-center bg-slate-950/75 px-5" role="status" aria-live="assertive" aria-busy="true"><div class="flex max-w-sm flex-col items-center rounded-2xl bg-white px-9 py-8 text-center shadow-2xl"><span class="loading-spinner" aria-hidden="true"></span><span class="mt-5 text-lg font-semibold text-slate-900">{{ busyLabel }}</span><span class="mt-2 text-sm text-slate-500">Please wait while this finishes.</span></div></div>
</template>
