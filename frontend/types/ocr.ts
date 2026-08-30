// frontend/types/ocr.ts
export interface BoundingBoxCoords {
  x: number      // Percentage (0-100)
  y: number      // Percentage (0-100)
  width: number  // Percentage (0-100)
  height: number // Percentage (0-100)
}

export interface ExtractedField {
  key: string
  label: string
  value: string
  confidence: number
  bbox?: BoundingBoxCoords
}

export interface OcrExtractionResult {
  imageUrl: string
  documentType: string
  fields: Record<string, ExtractedField>
}