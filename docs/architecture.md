# Architecture

## Design goals

- Keep the OCR vendor and model isolated from API contracts.
- Return suggested, editable values—not authoritative identity data.
- Keep saved records and original documents local to this backend instance.
- Keep field provenance so users can compare suggestions with their source.

## Backend layers

| Layer | Responsibility |
| --- | --- |
| `api` | HTTP validation, response codes, and dependency wiring |
| `services/ocr` | A provider protocol and the PaddleOCR implementation |
| `services/extraction` | Converts recognized text into field suggestions |
| `services/documents` | Validates images and renders bounded PDF pages |
| `services/storage` | Persists forms in SQLite and originals on disk |
| `schemas` | Stable request/response models shared by every client |

`PaddleOCREngine` converts engine output to page-specific `TextBlock` records. Extraction uses conservative label and pattern matching for Person and Organization fields. Each suggested field stores the source media ID and text-block index, letting the UI highlight its location.

## API contract

`POST /api/v1/documents/extract` uses `multipart/form-data` with `form_type` and an image or PDF file. It returns page metadata/previews, OCR text blocks, and field suggestions. Extraction does not persist the document; the reviewed form and original upload are saved together when the user finishes.

```json
{
  "document_id": "uuid",
  "pages": [{"index": 0, "width": 1600, "height": 900, "data_url": null}],
  "text_blocks": [{"text": "Name: Jane Doe", "confidence": 0.99, "page_index": 0, "bounding_box": [{"x": 0, "y": 0}, {"x": 200, "y": 0}, {"x": 200, "y": 30}, {"x": 0, "y": 30}]}],
  "fields": [{"key": "full_name", "label": "Full name", "value": "Jane Doe", "confidence": 0.99, "source_media_id": "uuid", "source_block_index": 0, "edited": false}]
}
```

`/api/v1/forms` creates and lists saved records. `/api/v1/forms/{id}` reads, edits, and deletes them. `/api/v1/forms/{id}/media` accepts `replace` or `add`; replace swaps all values and files, while add fills empty values and retains up to three files. Saved media and rendered PDF pages have read endpoints for the comparison view.

## Evolution path

1. Add accounts and per-user access controls before exposing private records on a network.
2. Add encrypted storage, backups, retention controls, and audit records for production use.
3. Move longer OCR processing into background jobs if PDF volume grows.
4. Improve extraction with document-specific templates and confidence review.
