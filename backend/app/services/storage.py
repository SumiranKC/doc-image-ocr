"""Local SQLite records and original uploaded media."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from uuid import uuid4

from fastapi import HTTPException

from app.config import Settings
from app.schemas import FORM_FIELDS, FieldValue, FormType, MediaItem, PagePreview, SavedForm, SavedFormSummary, TextBlock, UploadMode
from app.services.documents import MIME_EXTENSIONS


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class FormStore:
    def __init__(self, settings: Settings):
        self.media_dir = settings.data_dir / "media"
        self.media_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = settings.data_dir / "forms.sqlite3"
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS forms (
                    id TEXT PRIMARY KEY,
                    form_type TEXT NOT NULL,
                    fields_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS media (
                    id TEXT PRIMARY KEY,
                    form_id TEXT NOT NULL REFERENCES forms(id) ON DELETE CASCADE,
                    filename TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    page_count INTEGER NOT NULL,
                    pages_json TEXT NOT NULL,
                    text_blocks_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _media_path(self, media_id: str, mime_type: str) -> Path:
        return self.media_dir / f"{media_id}{MIME_EXTENSIONS[mime_type]}"

    def list_forms(self) -> list[SavedFormSummary]:
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT forms.*, COUNT(media.id) AS media_count
                FROM forms LEFT JOIN media ON media.form_id = forms.id
                GROUP BY forms.id ORDER BY forms.updated_at DESC
            """).fetchall()
        return [self._summary(row) for row in rows]

    def get_form(self, form_id: str) -> SavedForm:
        with self._connect() as conn:
            row = self._form_row(conn, form_id)
            media_rows = conn.execute(
                "SELECT * FROM media WHERE form_id = ? ORDER BY created_at, rowid", (form_id,)
            ).fetchall()
        summary = self._summary(row, len(media_rows))
        return SavedForm(
            **summary.model_dump(),
            fields=self._decode_fields(row["fields_json"]),
            media=[MediaItem(
                id=item["id"], filename=item["filename"], mime_type=item["mime_type"],
                page_count=item["page_count"],
                pages=[PagePreview.model_validate(page) for page in json.loads(item["pages_json"])],
                text_blocks=[TextBlock.model_validate(block) for block in json.loads(item["text_blocks_json"])],
            ) for item in media_rows],
        )

    def create_form(
        self, form_type: FormType, fields: dict[str, FieldValue],
        media_id: str, filename: str, mime_type: str, content: bytes,
        pages: list[PagePreview], blocks: list[TextBlock],
    ) -> SavedForm:
        self._validate_fields(form_type, fields)
        self._validate_sources(fields, {media_id})
        form_id = str(uuid4())
        timestamp = now()
        path = self._media_path(media_id, mime_type)
        with self._connect() as conn:
            if conn.execute("SELECT 1 FROM media WHERE id = ?", (media_id,)).fetchone():
                raise HTTPException(409, "This document was already saved.")
            path.write_bytes(content)
            try:
                with conn:
                    conn.execute("INSERT INTO forms VALUES (?, ?, ?, ?, ?)", (
                        form_id, form_type, self._encode_fields(fields), timestamp, timestamp,
                    ))
                    self._insert_media(conn, media_id, form_id, filename, mime_type, pages, blocks, timestamp)
            except Exception:
                path.unlink(missing_ok=True)
                raise
        return self.get_form(form_id)

    def update_fields(self, form_id: str, fields: dict[str, FieldValue]) -> SavedForm:
        current = self.get_form(form_id)
        self._validate_fields(current.form_type, fields)
        self._validate_sources(fields, {media.id for media in current.media})
        with self._connect() as conn, conn:
            conn.execute("UPDATE forms SET fields_json = ?, updated_at = ? WHERE id = ?", (
                self._encode_fields(fields), now(), form_id,
            ))
        return self.get_form(form_id)

    def upload_media(
        self, form_id: str, mode: UploadMode, incoming: dict[str, FieldValue],
        media_id: str, filename: str, mime_type: str, content: bytes,
        pages: list[PagePreview], blocks: list[TextBlock],
    ) -> SavedForm:
        current = self.get_form(form_id)
        self._validate_fields(current.form_type, incoming)
        if mode == "add" and len(current.media) >= 3:
            raise HTTPException(409, "A form can contain at most three documents.")
        fields = incoming if mode == "replace" else {
            key: current.fields[key] if current.fields[key].value.strip() else incoming[key]
            for key in FORM_FIELDS[current.form_type]
        }
        allowed_media = {media_id} if mode == "replace" else {media.id for media in current.media} | {media_id}
        self._validate_sources(fields, allowed_media)
        old_paths = [self._media_path(media.id, media.mime_type) for media in current.media] if mode == "replace" else []
        path = self._media_path(media_id, mime_type)
        timestamp = now()
        with self._connect() as conn:
            if conn.execute("SELECT 1 FROM media WHERE id = ?", (media_id,)).fetchone():
                raise HTTPException(409, "This document was already saved.")
            path.write_bytes(content)
            try:
                with conn:
                    if mode == "replace":
                        conn.execute("DELETE FROM media WHERE form_id = ?", (form_id,))
                    conn.execute("UPDATE forms SET fields_json = ?, updated_at = ? WHERE id = ?", (
                        self._encode_fields(fields), timestamp, form_id,
                    ))
                    self._insert_media(conn, media_id, form_id, filename, mime_type, pages, blocks, timestamp)
            except Exception:
                path.unlink(missing_ok=True)
                raise
        for old_path in old_paths:
            old_path.unlink(missing_ok=True)
        return self.get_form(form_id)

    def delete_form(self, form_id: str) -> None:
        current = self.get_form(form_id)
        with self._connect() as conn, conn:
            conn.execute("DELETE FROM forms WHERE id = ?", (form_id,))
        for media in current.media:
            self._media_path(media.id, media.mime_type).unlink(missing_ok=True)

    def media_path(self, form_id: str, media_id: str) -> tuple[Path, MediaItem]:
        current = self.get_form(form_id)
        media = next((item for item in current.media if item.id == media_id), None)
        if media is None:
            raise HTTPException(404, "Document not found.")
        path = self._media_path(media.id, media.mime_type)
        if not path.is_file():
            raise HTTPException(404, "Document file not found.")
        return path, media

    @staticmethod
    def _form_row(conn: sqlite3.Connection, form_id: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM forms WHERE id = ?", (form_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Form not found.")
        return row

    @staticmethod
    def _decode_fields(raw: str) -> dict[str, FieldValue]:
        return {key: FieldValue.model_validate(value) for key, value in json.loads(raw).items()}

    @staticmethod
    def _encode_fields(fields: dict[str, FieldValue]) -> str:
        return json.dumps({key: field.model_dump() for key, field in fields.items()})

    @staticmethod
    def _validate_fields(form_type: FormType, fields: dict[str, FieldValue]) -> None:
        if set(fields) != set(FORM_FIELDS[form_type]):
            raise HTTPException(422, "Fields do not match the selected form.")

    @staticmethod
    def _validate_sources(fields: dict[str, FieldValue], media_ids: set[str]) -> None:
        if any(field.source_media_id and field.source_media_id not in media_ids for field in fields.values()):
            raise HTTPException(422, "A field references an unavailable document.")

    @staticmethod
    def _insert_media(
        conn: sqlite3.Connection, media_id: str, form_id: str, filename: str,
        mime_type: str, pages: list[PagePreview], blocks: list[TextBlock], timestamp: str,
    ) -> None:
        conn.execute("INSERT INTO media VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (
            media_id, form_id, Path(filename).name, mime_type, len(pages),
            json.dumps([page.model_copy(update={"data_url": None}).model_dump() for page in pages]),
            json.dumps([block.model_dump() for block in blocks]), timestamp,
        ))

    @staticmethod
    def _summary(row: sqlite3.Row, media_count: int | None = None) -> SavedFormSummary:
        fields = FormStore._decode_fields(row["fields_json"])
        name_key = "full_name" if row["form_type"] == "person" else "organization_name"
        display_name = fields[name_key].value.strip() or f"Untitled {row['form_type']}"
        return SavedFormSummary(
            id=row["id"], form_type=row["form_type"], display_name=display_name,
            media_count=media_count if media_count is not None else row["media_count"],
            created_at=row["created_at"], updated_at=row["updated_at"],
        )
