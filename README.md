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
        └──► session-scoped SQLite records and saved original documents
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

Choose Contact Person or Organization, then upload a PNG, JPEG, WebP, or PDF (10 MB maximum, up to 10 PDF pages). Review the suggested values beside the document and select a highlighted field to see its source. "Finish and save" stores the form and original media temporarily in `backend/data/`.

The Person form's Organization field is plain text. The two form types are independent and there is no Capsule CRM connection.

The Saved forms page supports manual edits, deletion, and uploading another document. Replace discards all existing values and media after you save the new review. Add retains existing values, fills empty fields only, and keeps both documents; each form can hold at most three documents. Uploading does not change a saved record until you choose "Finish and save". A temporary session can contain at most five saved forms and 40 MB of original documents. Replacing media releases the replaced files' quota, and deleting a form releases all storage used by that form.

The app creates an anonymous session token in browser `sessionStorage`. All extraction, form, and media endpoints require that token, and records from one session are unavailable to another. The browser sends a heartbeat every minute while the app is open. Sessions expire one hour after their last authenticated request; the backend checks for expired sessions every five minutes and deletes their forms and original media. Closing the tab removes the browser's token, so the session cannot be reopened from that tab.

This is anonymous session isolation, not user authentication. The API allows at most 30 new sessions and 20 OCR requests globally per minute, at most six OCR requests per session per minute, and one active OCR job at a time. Excess requests receive `429 Too Many Requests` with a `Retry-After` header. These values can be changed with `MAX_SESSION_CREATIONS_PER_MINUTE`, `MAX_OCR_REQUESTS_PER_MINUTE`, `MAX_OCR_REQUESTS_PER_SESSION_PER_MINUTE`, and `MAX_CONCURRENT_OCR_JOBS`.

Run backend tests with `cd backend && .venv/bin/python -m unittest discover -s tests -v` and build the frontend with `cd frontend && npm run build`.

## Run the backend with Docker

Build from the backend directory so Railway and local Docker use the same build context:

```bash
cd backend
docker build --tag document-ocr-api .
docker run --rm --publish 8000:8000 --env ALLOWED_ORIGINS='["http://localhost:5173"]' --volume document-ocr-data:/data document-ocr-api
```

The production image uses one Uvicorn worker, stores session data under `/data`, and downloads the English PaddleOCR models while building. Railway should use `backend/` as the service root, mount its volume at `/data`, and set `RAILWAY_RUN_UID=0` because Railway mounts volumes as root. The container still runs as the unprivileged `app` user everywhere else.

## Deploy the backend to Railway

The supported Railway Infrastructure-as-Code definition is in `.railway/railway.ts`. It declares the GitHub backend source, `/health` deployment check, GitHub Pages CORS origin, and a 500 MB `/data` volume in Singapore.

Commit and push the current changes, create an empty Railway project, and then run:

```bash
cd .railway
npm install
cd ..
railway login
railway link
railway config plan
railway config apply
```

Review the plan before applying it. After the deployment succeeds, generate a public domain for the `backend` service and verify `https://YOUR-DOMAIN/health`. Keep a single backend instance because the application uses SQLite, process-local rate limits, and one in-memory OCR engine.
