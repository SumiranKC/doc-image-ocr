from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


FormType = Literal["person", "organization"]
UploadMode = Literal["replace", "add"]

FORM_FIELDS: dict[str, tuple[str, ...]] = {
    "person": (
        "full_name", "title", "job_title", "organization", "email", "phone",
        "website", "address", "notes",
    ),
    "organization": (
        "organization_name", "email", "phone", "website", "address", "description",
    ),
}


class Point(BaseModel):
    x: float
    y: float


class TextBlock(BaseModel):
    text: str
    confidence: float = Field(ge=0, le=1)
    bounding_box: list[Point]
    page_index: int = Field(default=0, ge=0)


class FieldValue(BaseModel):
    value: str = Field(default="", max_length=4000)
    confidence: float | None = Field(default=None, ge=0, le=1)
    source_media_id: str | None = None
    source_block_index: int | None = Field(default=None, ge=0)
    edited: bool = False


class ExtractedField(FieldValue):
    key: str
    label: str


class PagePreview(BaseModel):
    index: int
    width: int
    height: int
    data_url: str | None = None


class ExtractionResponse(BaseModel):
    document_id: str
    pages: list[PagePreview]
    text_blocks: list[TextBlock]
    fields: list[ExtractedField]


class SessionCreated(BaseModel):
    token: str
    expires_at: datetime


class MediaItem(BaseModel):
    id: str
    filename: str
    mime_type: str
    page_count: int
    pages: list[PagePreview]
    text_blocks: list[TextBlock]


class SavedFormSummary(BaseModel):
    id: str
    form_type: FormType
    display_name: str
    media_count: int
    created_at: datetime
    updated_at: datetime


class SavedForm(SavedFormSummary):
    fields: dict[str, FieldValue]
    media: list[MediaItem]


class UpdateFields(BaseModel):
    fields: dict[str, FieldValue]
