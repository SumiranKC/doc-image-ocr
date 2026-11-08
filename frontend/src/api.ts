export type FormType = 'person' | 'organization'
export type UploadMode = 'replace' | 'add'
export type Point = { x: number; y: number }
export type TextBlock = {
  text: string
  confidence: number
  bounding_box: Point[]
  page_index: number
}
export type FieldValue = {
  value: string
  confidence: number | null
  source_media_id: string | null
  source_block_index: number | null
  edited: boolean
}
export type ExtractedField = FieldValue & { key: string; label: string }
export type PagePreview = { index: number; width: number; height: number; data_url: string | null }
export type ExtractionResponse = {
  document_id: string
  pages: PagePreview[]
  text_blocks: TextBlock[]
  fields: ExtractedField[]
}
export type MediaItem = {
  id: string
  filename: string
  mime_type: string
  page_count: number
  pages: PagePreview[]
  text_blocks: TextBlock[]
}
export type SavedFormSummary = {
  id: string
  form_type: FormType
  display_name: string
  media_count: number
  created_at: string
  updated_at: string
}
export type SavedForm = SavedFormSummary & { fields: Record<string, FieldValue>; media: MediaItem[] }

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, options)
  if (!response.ok) {
    const error = await response.json().catch(() => null)
    throw new Error(typeof error?.detail === 'string' ? error.detail : `Request failed (${response.status})`)
  }
  if (response.status === 204) return undefined as T
  return response.json()
}

export function mediaPageUrl(formId: string, mediaId: string, pageIndex: number): string {
  return `${apiBaseUrl}/api/v1/forms/${formId}/media/${mediaId}/pages/${pageIndex}`
}

export function originalMediaUrl(formId: string, mediaId: string): string {
  return `${apiBaseUrl}/api/v1/forms/${formId}/media/${mediaId}`
}

export async function extractDocument(file: File, formType: FormType): Promise<ExtractionResponse> {
  const body = new FormData()
  body.append('file', file)
  body.append('form_type', formType)
  return request('/api/v1/documents/extract', { method: 'POST', body })
}

export function listSavedForms(): Promise<SavedFormSummary[]> {
  return request('/api/v1/forms')
}

export function getSavedForm(id: string): Promise<SavedForm> {
  return request(`/api/v1/forms/${id}`)
}

function draftBody(file: File, draft: ExtractionResponse, fields: Record<string, FieldValue>): FormData {
  const body = new FormData()
  body.append('file', file)
  body.append('document_id', draft.document_id)
  body.append('fields_json', JSON.stringify(fields))
  body.append('text_blocks_json', JSON.stringify(draft.text_blocks))
  return body
}

export function createSavedForm(
  formType: FormType, file: File, draft: ExtractionResponse, fields: Record<string, FieldValue>,
): Promise<SavedForm> {
  const body = draftBody(file, draft, fields)
  body.append('form_type', formType)
  return request('/api/v1/forms', { method: 'POST', body })
}

export function saveUploadedMedia(
  formId: string, mode: UploadMode, file: File, draft: ExtractionResponse,
  fields: Record<string, FieldValue>,
): Promise<SavedForm> {
  const body = draftBody(file, draft, fields)
  body.append('mode', mode)
  return request(`/api/v1/forms/${formId}/media`, { method: 'POST', body })
}

export function updateSavedForm(formId: string, fields: Record<string, FieldValue>): Promise<SavedForm> {
  return request(`/api/v1/forms/${formId}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ fields }),
  })
}

export function deleteSavedForm(formId: string): Promise<void> {
  return request(`/api/v1/forms/${formId}`, { method: 'DELETE' })
}
