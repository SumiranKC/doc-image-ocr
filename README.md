# Document OCR

An OCR app for filling and reviewing contact forms from documents. It uses PaddleOCR, FastAPI, Vue 3, TypeScript, and Tailwind CSS.

## Architecture

```text
browser (Vue + TypeScript)
        │ choose form, upload image / PDF
        ▼
FastAPI API ──► document validation and page rendering
        │
        ├──► OCR engine adapter (PaddleOCR) ──► text blocks with coordinates
        ├──► form-specific field suggestions
        └──► SQLite records and saved original documents
                        │
                        ▼
           side-by-side review and saved forms
```

The API deliberately exposes normalized `TextBlock` and `ExtractedField` data rather than PaddleOCR-specific output. That keeps OCR engines, document classifiers, and downstream integrations replaceable.

## Layout

- `backend/` — FastAPI service, OCR provider interface, field extraction, SQLite storage, API schemas.
- `frontend/` — Vue form selection, document review, and saved-record pages.
- `docs/architecture.md` — component boundaries and a suggested growth path.

## Run locally

Backend (Python 3.13 supported):

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Frontend (Node 20+):

```bash
cd frontend
npm install
npm run dev
```

Visit the Vite URL (normally `http://localhost:5173`). The frontend expects the API at `http://localhost:8000`; set `VITE_API_BASE_URL` to change it.

Choose Contact Person or Organization, then upload a PNG, JPEG, WebP, or PDF (10 MB maximum, up to 10 PDF pages). Review the suggested values beside the document and select a highlighted field to see its source. "Finish and save" stores the form and original media locally in `backend/data/`.

The Person form's Organization field is plain text. The two form types are independent and there is no Capsule CRM connection.

The Saved forms page supports manual edits, deletion, and uploading another document. Replace discards all existing values and media after you save the new review. Add retains existing values, fills empty fields only, and keeps both documents; each form can hold at most three documents. Uploading does not change a saved record until you choose "Finish and save".

Saved records are local to this backend instance. This MVP has no accounts or access controls, so do not expose the API on a public network with private documents. PaddleOCR downloads its local models on first use.

Run backend tests with `cd backend && .venv/bin/python -m unittest discover -s tests -v` and build the frontend with `cd frontend && npm run build`.
