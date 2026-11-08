import json
from functools import lru_cache
from io import BytesIO
from uuid import UUID
from uuid import uuid4

import pypdfium2 as pdfium
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import TypeAdapter, ValidationError
from starlette.concurrency import run_in_threadpool

from app.config import Settings, get_settings
from app.schemas import (
    ExtractionResponse, FieldValue, FormType, SavedForm, SavedFormSummary,
    TextBlock, UpdateFields, UploadMode,
)
from app.services.documents import MIME_EXTENSIONS, prepare_document, render_pdf_page
from app.services.extraction import extract_fields
from app.services.ocr import OCREngine, PaddleOCREngine
from app.services.storage import FormStore


@lru_cache
def get_ocr_engine() -> OCREngine:
    return PaddleOCREngine()


def get_store(app_settings: Settings = Depends(get_settings)) -> FormStore:
    return FormStore(app_settings)


settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0")
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


@app.post("/api/v1/documents/extract", response_model=ExtractionResponse)
async def extract_document(
    file: UploadFile = File(...),
    form_type: FormType = Form(...),
    app_settings: Settings = Depends(get_settings),
    engine: OCREngine = Depends(get_ocr_engine),
) -> ExtractionResponse:
    content, mime_type = await read_upload(file, app_settings)
    prepared = await run_in_threadpool(prepare_document, content, mime_type, app_settings.max_pdf_pages)
    blocks = await run_in_threadpool(engine.recognize, prepared.images)
    media_id = str(uuid4())
    return ExtractionResponse(
        document_id=media_id, pages=prepared.previews,
        text_blocks=blocks, fields=extract_fields(blocks, form_type, media_id),
    )


@app.get("/api/v1/forms", response_model=list[SavedFormSummary])
def list_forms(store: FormStore = Depends(get_store)) -> list[SavedFormSummary]:
    return store.list_forms()


@app.get("/api/v1/forms/{form_id}", response_model=SavedForm)
def get_form(form_id: str, store: FormStore = Depends(get_store)) -> SavedForm:
    return store.get_form(form_id)


@app.post("/api/v1/forms", response_model=SavedForm, status_code=201)
async def create_form(
    form_type: FormType = Form(...),
    fields_json: str = Form(...),
    text_blocks_json: str = Form(...),
    document_id: UUID = Form(...),
    file: UploadFile = File(...),
    store: FormStore = Depends(get_store),
    app_settings: Settings = Depends(get_settings),
) -> SavedForm:
    content, mime_type = await read_upload(file, app_settings)
    prepared = await run_in_threadpool(prepare_document, content, mime_type, app_settings.max_pdf_pages, False)
    fields = parse_fields(fields_json)
    blocks = parse_blocks(text_blocks_json, prepared.previews)
    return await run_in_threadpool(
        store.create_form, form_type, fields, str(document_id), file.filename or "document",
        mime_type, content, prepared.previews, blocks,
    )


@app.put("/api/v1/forms/{form_id}", response_model=SavedForm)
def update_form(
    form_id: str, request: UpdateFields, store: FormStore = Depends(get_store),
) -> SavedForm:
    return store.update_fields(form_id, request.fields)


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
) -> SavedForm:
    content, mime_type = await read_upload(file, app_settings)
    prepared = await run_in_threadpool(prepare_document, content, mime_type, app_settings.max_pdf_pages, False)
    fields = parse_fields(fields_json)
    blocks = parse_blocks(text_blocks_json, prepared.previews)
    return await run_in_threadpool(
        store.upload_media, form_id, mode, fields, str(document_id),
        file.filename or "document", mime_type, content, prepared.previews, blocks,
    )


@app.delete("/api/v1/forms/{form_id}", status_code=204)
def delete_form(form_id: str, store: FormStore = Depends(get_store)) -> Response:
    store.delete_form(form_id)
    return Response(status_code=204)


@app.get("/api/v1/forms/{form_id}/media/{media_id}")
def get_media(
    form_id: str, media_id: str, store: FormStore = Depends(get_store),
) -> FileResponse:
    path, media = store.media_path(form_id, media_id)
    return FileResponse(
        path, media_type=media.mime_type, filename=media.filename,
        content_disposition_type="inline",
    )


@app.get("/api/v1/forms/{form_id}/media/{media_id}/pages/{page_index}")
def get_media_page(
    form_id: str, media_id: str, page_index: int, store: FormStore = Depends(get_store),
) -> Response:
    path, media = store.media_path(form_id, media_id)
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
