# Architecture

## Design goals

- Keep the OCR vendor and model isolated from API contracts.
- Return suggested, editable values—not authoritative identity data.
- Isolate saved records and original documents in short-lived anonymous sessions.
- Keep field provenance so users can compare suggestions with their source.

## Backend layers

| Layer | Responsibility |
| --- | --- |
| `api` | HTTP validation, response codes, and dependency wiring |
| `services/ocr` | A provider protocol and the PaddleOCR implementation |
| `services/extraction` | Converts recognized text into field suggestions |
| `services/documents` | Validates images and renders bounded PDF pages |
| `services/storage` | Owns anonymous sessions and persists their forms in SQLite and originals on disk |
| `schemas` | Stable request/response models shared by every client |

`PaddleOCREngine` converts engine output to page-specific `TextBlock` records. Extraction uses conservative label and pattern matching for Person and Organization fields. Each suggested field stores the source media ID and text-block index, letting the UI highlight its location.

## API contract

`POST /api/v1/sessions` creates an anonymous temporary session and returns a bearer token. The frontend keeps the token in `sessionStorage`; every other `/api/v1` endpoint requires it in the `Authorization` header. `POST /api/v1/sessions/heartbeat` and all authenticated requests extend the session for one hour.

`POST /api/v1/documents/extract` uses `multipart/form-data` with `form_type` and an image or PDF file. It returns page metadata/previews, OCR text blocks, and field suggestions. Extraction does not persist the document; the reviewed form and original upload are saved together when the user finishes.

```json
{
  "document_id": "uuid",
  "pages": [{"index": 0, "width": 1600, "height": 900, "data_url": null}],
  "text_blocks": [{"text": "Name: Jane Doe", "confidence": 0.99, "page_index": 0, "bounding_box": [{"x": 0, "y": 0}, {"x": 200, "y": 0}, {"x": 200, "y": 30}, {"x": 0, "y": 30}]}],
  "fields": [{"key": "full_name", "label": "Full name", "value": "Jane Doe", "confidence": 0.99, "source_media_id": "uuid", "source_block_index": 0, "edited": false}]
}
```

`/api/v1/forms` creates and lists records owned by the current session. `/api/v1/forms/{id}` reads, edits, and deletes only records from that session. `/api/v1/forms/{id}/media` accepts `replace` or `add`; replace swaps all values and files, while add fills empty values and retains up to three files. Saved media and rendered PDF pages use the same session boundary and are fetched as authenticated blobs by the frontend.

The frontend sends a heartbeat every minute. A backend lifecycle task checks every five minutes for sessions whose last activity was more than one hour ago. Cleanup deletes the session's database records and media files. Records created before session support are preserved as inaccessible legacy rows rather than assigned to an arbitrary visitor.

Storage enforces two per-session quotas inside SQLite write transactions: no more than five saved forms and no more than 40 MB of original media. Media rows record their byte size, including a migration that backfills sizes from existing files. Add uploads consume more quota; replace uploads subtract the replaced form's media before checking the new total; deleting a form releases its media quota.

The production backend is packaged from `backend/Dockerfile`. It uses a slim Python 3.12 Linux base, installs the native CPU libraries required by PaddleOCR, downloads the English detection and recognition models during the image build, runs as an unprivileged user, and starts one Uvicorn worker. Application code and OCR models are immutable image content; the SQLite database and session media live on the separately mounted `/data` volume.

Process-local sliding-window limits cap session creation and both global and per-session OCR request rates. A bounded semaphore permits only the configured number of OCR jobs to run at once; extra work is rejected with `429` and a `Retry-After` header instead of allowing CPU and memory use to grow without bounds. These controls are consistent because the production container intentionally runs one Uvicorn worker.

## Evolution path

1. Move longer OCR processing into background jobs if PDF volume grows.
2. Improve extraction with document-specific templates and confidence review.
