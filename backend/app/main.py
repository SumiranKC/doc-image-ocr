import asyncio
import json
import logging
from contextlib import asynccontextmanager, suppress
from functools import lru_cache
from io import BytesIO
from typing import Annotated
from uuid import UUID
from uuid import uuid4

import pypdfium2 as pdfium
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import TypeAdapter, ValidationError
from starlette.concurrency import run_in_threadpool

from app.config import Settings, get_settings
from app.schemas import (
    ExtractionResponse, FieldValue, FormType, SavedForm, SavedFormSummary,
    SessionCreated, TextBlock, UpdateFields, UploadMode,
)
from app.services.documents import MIME_EXTENSIONS, prepare_document, render_pdf_page
from app.services.extraction import extract_fields
from app.services.limits import RequestLimits
from app.services.ocr import OCREngine, PaddleOCREngine
from app.services.storage import FormStore


logger = logging.getLogger(__name__)
bearer_scheme = HTTPBearer(auto_error=False)


@lru_cache
def get_ocr_engine() -> OCREngine:
    return PaddleOCREngine()


def get_store(app_settings: Settings = Depends(get_settings)) -> FormStore:
    return FormStore(app_settings)


@lru_cache
def build_request_limits(
    session_creations_per_minute: int,
    global_ocr_per_minute: int,
    session_ocr_per_minute: int,
    concurrent_ocr_jobs: int,
) -> RequestLimits:
    return RequestLimits(
        session_creations_per_minute,
        global_ocr_per_minute,
        session_ocr_per_minute,
        concurrent_ocr_jobs,
    )


def get_request_limits(
    app_settings: Settings = Depends(get_settings),
) -> RequestLimits:
    return build_request_limits(
        app_settings.max_session_creations_per_minute,
        app_settings.max_ocr_requests_per_minute,
        app_settings.max_ocr_requests_per_session_per_minute,
        app_settings.max_concurrent_ocr_jobs,
    )


def get_session_id(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ],
    store: Annotated[FormStore, Depends(get_store)],
) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(401, "A temporary session is required.")
    return store.authenticate_session(credentials.credentials)


async def cleanup_expired_sessions(stop: asyncio.Event) -> None:
    app_settings = get_settings()
    store = FormStore(app_settings)
    while True:
        try:
            await asyncio.wait_for(
                stop.wait(), timeout=app_settings.session_cleanup_interval_seconds
            )
            return
        except TimeoutError:
            try:
                await run_in_threadpool(store.cleanup_expired_sessions)
            except Exception:
                logger.exception("Temporary session cleanup failed.")


@asynccontextmanager
async def lifespan(_: FastAPI):
    stop = asyncio.Event()
    cleanup_task = asyncio.create_task(cleanup_expired_sessions(stop))
    try:
        yield
    finally:
        stop.set()
        cleanup_task.cancel()
        with suppress(asyncio.CancelledError):
            await cleanup_task


settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/sessions", response_model=SessionCreated, status_code=201)
def create_session(
    store: FormStore = Depends(get_store),
    limits: RequestLimits = Depends(get_request_limits),
) -> SessionCreated:
    retry_after = limits.check_session_creation()
    if retry_after is not None:
        raise HTTPException(
            429, "Too many temporary sessions have been started. Please try again shortly.",
            headers={"Retry-After": str(retry_after)},
        )
    token, expires_at = store.create_session()
    return SessionCreated(token=token, expires_at=expires_at)


@app.post("/api/v1/sessions/heartbeat", status_code=204)
def heartbeat(_: str = Depends(get_session_id)) -> Response:
    return Response(status_code=204)


@app.post("/api/v1/documents/extract", response_model=ExtractionResponse)
async def extract_document(
    file: UploadFile = File(...),
    form_type: FormType = Form(...),
    app_settings: Settings = Depends(get_settings),
    engine: OCREngine = Depends(get_ocr_engine),
    session_id: str = Depends(get_session_id),
    limits: RequestLimits = Depends(get_request_limits),
) -> ExtractionResponse:
    retry_after = limits.check_ocr(session_id)
    if retry_after is not None:
        raise HTTPException(
            429, "Too many documents were processed recently. Please try again shortly.",
            headers={"Retry-After": str(retry_after)},
        )
    if not limits.acquire_ocr_slot():
        raise HTTPException(
            429, "The OCR service is busy. Please try again shortly.",
            headers={"Retry-After": "5"},
        )
    try:
        content, mime_type = await read_upload(file, app_settings)
        prepared = await run_in_threadpool(
            prepare_document, content, mime_type, app_settings.max_pdf_pages
        )
        blocks = await run_in_threadpool(engine.recognize, prepared.images)
        media_id = str(uuid4())
        return ExtractionResponse(
            document_id=media_id, pages=prepared.previews,
            text_blocks=blocks, fields=extract_fields(blocks, form_type, media_id),
        )
    finally:
        limits.release_ocr_slot()


@app.get("/api/v1/forms", response_model=list[SavedFormSummary])
def list_forms(
    session_id: str = Depends(get_session_id), store: FormStore = Depends(get_store),
) -> list[SavedFormSummary]:
    return store.list_forms(session_id)


@app.get("/api/v1/forms/{form_id}", response_model=SavedForm)
def get_form(
    form_id: str, session_id: str = Depends(get_session_id),
    store: FormStore = Depends(get_store),
) -> SavedForm:
    return store.get_form(session_id, form_id)


@app.post("/api/v1/forms", response_model=SavedForm, status_code=201)
async def create_form(
    form_type: FormType = Form(...),
    fields_json: str = Form(...),
    text_blocks_json: str = Form(...),
    document_id: UUID = Form(...),
    file: UploadFile = File(...),
    store: FormStore = Depends(get_store),
    app_settings: Settings = Depends(get_settings),
    session_id: str = Depends(get_session_id),
) -> SavedForm:
    content, mime_type = await read_upload(file, app_settings)
    prepared = await run_in_threadpool(prepare_document, content, mime_type, app_settings.max_pdf_pages, False)
    fields = parse_fields(fields_json)
    blocks = parse_blocks(text_blocks_json, prepared.previews)
    return await run_in_threadpool(
        store.create_form, session_id, form_type, fields, str(document_id),
        file.filename or "document", mime_type, content, prepared.previews, blocks,
    )


@app.put("/api/v1/forms/{form_id}", response_model=SavedForm)
def update_form(
    form_id: str, request: UpdateFields,
    session_id: str = Depends(get_session_id), store: FormStore = Depends(get_store),
) -> SavedForm:
    return store.update_fields(session_id, form_id, request.fields)


@app.post("/api/v1/forms/{form_id}/media", response_model=SavedForm)
async def upload_form_media(
    form_id: str,
    mode: UploadMode = Form(...),
    fields_json: str = Form(...),
    text_blocks_json: str = Form(...),
    document_id: UUID = Form(...),
    file: UploadFile = File(...),
    store: FormStore = Depends(get_store),
    app_settings: Settings = Depends(get_settings),
    session_id: str = Depends(get_session_id),
) -> SavedForm:
    content, mime_type = await read_upload(file, app_settings)
    prepared = await run_in_threadpool(prepare_document, content, mime_type, app_settings.max_pdf_pages, False)
    fields = parse_fields(fields_json)
    blocks = parse_blocks(text_blocks_json, prepared.previews)
    return await run_in_threadpool(
        store.upload_media, session_id, form_id, mode, fields, str(document_id),
        file.filename or "document", mime_type, content, prepared.previews, blocks,
    )


@app.delete("/api/v1/forms/{form_id}", status_code=204)
def delete_form(
    form_id: str, session_id: str = Depends(get_session_id),
    store: FormStore = Depends(get_store),
) -> Response:
    store.delete_form(session_id, form_id)
    return Response(status_code=204)


@app.get("/api/v1/forms/{form_id}/media/{media_id}")
def get_media(
    form_id: str, media_id: str, session_id: str = Depends(get_session_id),
    store: FormStore = Depends(get_store),
) -> FileResponse:
    path, media = store.media_path(session_id, form_id, media_id)
    return FileResponse(
        path, media_type=media.mime_type, filename=media.filename,
        content_disposition_type="inline",
    )


@app.get("/api/v1/forms/{form_id}/media/{media_id}/pages/{page_index}")
def get_media_page(
    form_id: str, media_id: str, page_index: int,
    session_id: str = Depends(get_session_id), store: FormStore = Depends(get_store),
) -> Response:
    path, media = store.media_path(session_id, form_id, media_id)
    if page_index < 0 or page_index >= media.page_count:
        raise HTTPException(404, "Page not found.")
    if media.mime_type != "application/pdf":
        return FileResponse(path, media_type=media.mime_type)
    try:
        pdf = pdfium.PdfDocument(path.read_bytes())
        try:
            image = render_pdf_page(pdf, page_index)
        finally:
            pdf.close()
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return Response(buffer.getvalue(), media_type="image/png")
    except (ValueError, OSError, pdfium.PdfiumError) as exc:
        raise HTTPException(422, "The saved PDF could not be rendered.") from exc


async def read_upload(file: UploadFile, app_settings: Settings) -> tuple[bytes, str]:
    mime_type = file.content_type or ""
    if mime_type not in MIME_EXTENSIONS:
        raise HTTPException(415, "Upload a JPEG, PNG, WebP, or PDF document.")
    content = await file.read(app_settings.max_upload_bytes + 1)
    if not content or len(content) > app_settings.max_upload_bytes:
        raise HTTPException(413, "File must be between 1 byte and 10 MB.")
    return content, mime_type


def parse_fields(raw: str) -> dict[str, FieldValue]:
    try:
        return TypeAdapter(dict[str, FieldValue]).validate_python(json.loads(raw))
    except (ValueError, ValidationError) as exc:
        raise HTTPException(422, "Invalid form fields.") from exc


def parse_blocks(raw: str, pages: list) -> list[TextBlock]:
    try:
        blocks = TypeAdapter(list[TextBlock]).validate_python(json.loads(raw))
    except (ValueError, ValidationError) as exc:
        raise HTTPException(422, "Invalid recognized text.") from exc
    if any(block.page_index >= len(pages) or len(block.bounding_box) != 4 for block in blocks):
        raise HTTPException(422, "Recognized text references an invalid page.")
    return blocks
