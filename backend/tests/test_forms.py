import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings, get_settings
from app.main import app, build_request_limits, get_ocr_engine
from app.schemas import FORM_FIELDS, Point, TextBlock
from app.services.storage import FormStore


class FakeOCREngine:
    def recognize(self, images: list[Image.Image]) -> list[TextBlock]:
        return [
            TextBlock(
                text="Name: Alice Example", confidence=0.99,
                bounding_box=[Point(x=5, y=5), Point(x=160, y=5), Point(x=160, y=30), Point(x=5, y=30)],
                page_index=0,
            ),
            TextBlock(
                text="alice@example.com", confidence=0.97,
                bounding_box=[Point(x=5, y=35), Point(x=180, y=35), Point(x=180, y=55), Point(x=5, y=55)],
                page_index=0,
            ),
        ]


class FakeOrganizationOCR:
    def recognize(self, images: list[Image.Image]) -> list[TextBlock]:
        return [TextBlock(
            text="Company: Example Studio", confidence=0.96,
            bounding_box=[Point(x=5, y=5), Point(x=210, y=5), Point(x=210, y=30), Point(x=5, y=30)],
            page_index=0,
        )]


class FormWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.settings = Settings(data_dir=Path(self.directory.name))
        app.dependency_overrides[get_settings] = lambda: self.settings
        app.dependency_overrides[get_ocr_engine] = FakeOCREngine
        self.client = TestClient(app)
        self.headers = self.create_session_headers()
        buffer = BytesIO()
        Image.new("RGB", (300, 160), "white").save(buffer, format="PNG")
        self.png = buffer.getvalue()

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        build_request_limits.cache_clear()
        self.client.close()
        self.directory.cleanup()

    def create_session_headers(self) -> dict[str, str]:
        response = self.client.post("/api/v1/sessions")
        self.assertEqual(response.status_code, 201, response.text)
        return {"Authorization": f"Bearer {response.json()['token']}"}

    def extract(self, content: bytes | None = None, mime: str = "image/png", filename: str = "card.png") -> dict:
        response = self.client.post(
            "/api/v1/documents/extract",
            data={"form_type": "person"},
            files={"file": (filename, content or self.png, mime)},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def values(self, extraction: dict) -> dict:
        fields = {key: {
            "value": "", "confidence": None, "source_media_id": None,
            "source_block_index": None, "edited": False,
        } for key in FORM_FIELDS["person"]}
        for suggestion in extraction["fields"]:
            fields[suggestion["key"]] = {
                key: suggestion[key] for key in (
                    "value", "confidence", "source_media_id", "source_block_index", "edited",
                )
            }
        return fields

    def upload(self, extraction: dict, fields: dict, path: str, mode: str | None = None,
               content: bytes | None = None, mime: str = "image/png", filename: str = "card.png"):
        data = {
            "document_id": extraction["document_id"],
            "fields_json": json.dumps(fields),
            "text_blocks_json": json.dumps(extraction["text_blocks"]),
        }
        if mode:
            data["mode"] = mode
        else:
            data["form_type"] = "person"
        return self.client.post(
            path, data=data, files={"file": (filename, content or self.png, mime)},
            headers=self.headers,
        )

    def test_create_edit_add_replace_delete(self) -> None:
        first = self.extract()
        created = self.upload(first, self.values(first), "/api/v1/forms")
        self.assertEqual(created.status_code, 201, created.text)
        form = created.json()
        form_id = form["id"]
        first_path = Path(self.directory.name) / "media" / f"{first['document_id']}.png"
        self.assertTrue(first_path.is_file())
        self.assertEqual(form["fields"]["full_name"]["value"], "Alice Example")
        self.assertEqual(len(self.client.get("/api/v1/forms", headers=self.headers).json()), 1)

        edited = form["fields"]
        edited["job_title"]["value"] = "Director"
        edited["job_title"]["edited"] = True
        response = self.client.put(
            f"/api/v1/forms/{form_id}", json={"fields": edited}, headers=self.headers
        )
        self.assertEqual(response.status_code, 200, response.text)

        second = self.extract()
        incoming = self.values(second)
        incoming["full_name"]["value"] = "Should not replace Alice"
        incoming["organization"]["value"] = "Example Co"
        added = self.upload(second, incoming, f"/api/v1/forms/{form_id}/media", "add")
        self.assertEqual(added.status_code, 200, added.text)
        self.assertEqual(added.json()["fields"]["full_name"]["value"], "Alice Example")
        self.assertEqual(added.json()["fields"]["job_title"]["value"], "Director")
        self.assertEqual(added.json()["fields"]["organization"]["value"], "Example Co")
        self.assertEqual(len(added.json()["media"]), 2)

        third = self.extract()
        self.assertEqual(self.upload(third, self.values(third), f"/api/v1/forms/{form_id}/media", "add").status_code, 200)
        fourth = self.extract()
        self.assertEqual(self.upload(fourth, self.values(fourth), f"/api/v1/forms/{form_id}/media", "add").status_code, 409)

        replacement = self.extract()
        replacement_fields = self.values(replacement)
        replacement_fields["full_name"]["value"] = "New Contact"
        replaced = self.upload(replacement, replacement_fields, f"/api/v1/forms/{form_id}/media", "replace")
        self.assertEqual(replaced.status_code, 200, replaced.text)
        self.assertEqual(len(replaced.json()["media"]), 1)
        self.assertEqual(replaced.json()["fields"]["job_title"]["value"], "")
        self.assertFalse(first_path.exists())
        self.assertEqual(self.client.get(
            f"/api/v1/forms/{form_id}/media/{first['document_id']}", headers=self.headers
        ).status_code, 404)
        self.assertEqual(self.client.get(
            f"/api/v1/forms/{form_id}/media/{replacement['document_id']}/pages/0",
            headers=self.headers,
        ).status_code, 200)

        self.assertEqual(self.client.delete(
            f"/api/v1/forms/{form_id}", headers=self.headers
        ).status_code, 204)
        self.assertEqual(self.client.get(
            f"/api/v1/forms/{form_id}", headers=self.headers
        ).status_code, 404)
        self.assertFalse(any((Path(self.directory.name) / "media").iterdir()))

    def test_pdf_preview_and_save(self) -> None:
        buffer = BytesIO()
        Image.new("RGB", (300, 160), "white").save(
            buffer, format="PDF", save_all=True,
            append_images=[Image.new("RGB", (300, 160), "white")],
        )
        pdf = buffer.getvalue()
        extraction = self.extract(pdf, "application/pdf", "card.pdf")
        self.assertEqual(len(extraction["pages"]), 2)
        self.assertTrue(extraction["pages"][0]["data_url"].startswith("data:image/png;base64,"))
        created = self.upload(extraction, self.values(extraction), "/api/v1/forms", content=pdf,
                              mime="application/pdf", filename="card.pdf")
        self.assertEqual(created.status_code, 201, created.text)
        record = created.json()
        preview = self.client.get(
            f"/api/v1/forms/{record['id']}/media/{extraction['document_id']}/pages/1",
            headers=self.headers,
        )
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertEqual(preview.headers["content-type"], "image/png")
        self.assertEqual(preview.content[:8], b"\x89PNG\r\n\x1a\n")

    def test_organization_form_uses_its_own_fields(self) -> None:
        app.dependency_overrides[get_ocr_engine] = FakeOrganizationOCR
        extracted = self.client.post(
            "/api/v1/documents/extract", data={"form_type": "organization"},
            files={"file": ("company.png", self.png, "image/png")},
            headers=self.headers,
        )
        self.assertEqual(extracted.status_code, 200, extracted.text)
        result = extracted.json()
        self.assertEqual([field["key"] for field in result["fields"]], ["organization_name"])
        fields = {key: {
            "value": "", "confidence": None, "source_media_id": None,
            "source_block_index": None, "edited": False,
        } for key in FORM_FIELDS["organization"]}
        fields["organization_name"] = {
            key: result["fields"][0][key] for key in (
                "value", "confidence", "source_media_id", "source_block_index", "edited",
            )
        }
        saved = self.client.post(
            "/api/v1/forms",
            data={
                "form_type": "organization", "document_id": result["document_id"],
                "fields_json": json.dumps(fields), "text_blocks_json": json.dumps(result["text_blocks"]),
            },
            files={"file": ("company.png", self.png, "image/png")},
            headers=self.headers,
        )
        self.assertEqual(saved.status_code, 201, saved.text)
        self.assertEqual(saved.json()["display_name"], "Example Studio")

    def test_sessions_are_isolated_and_required(self) -> None:
        extraction = self.extract()
        created = self.upload(extraction, self.values(extraction), "/api/v1/forms")
        self.assertEqual(created.status_code, 201, created.text)
        form_id = created.json()["id"]
        media_id = extraction["document_id"]
        other_headers = self.create_session_headers()

        self.assertEqual(self.client.get("/api/v1/forms").status_code, 401)
        self.assertEqual(self.client.get(
            "/api/v1/forms", headers=other_headers
        ).json(), [])
        self.assertEqual(self.client.get(
            f"/api/v1/forms/{form_id}", headers=other_headers
        ).status_code, 404)
        self.assertEqual(self.client.get(
            f"/api/v1/forms/{form_id}/media/{media_id}", headers=other_headers
        ).status_code, 404)
        self.assertEqual(self.client.delete(
            f"/api/v1/forms/{form_id}", headers=other_headers
        ).status_code, 404)
        self.assertEqual(self.client.get(
            f"/api/v1/forms/{form_id}", headers=self.headers
        ).status_code, 200)

    def test_expired_session_and_its_media_are_deleted(self) -> None:
        extraction = self.extract()
        created = self.upload(extraction, self.values(extraction), "/api/v1/forms")
        self.assertEqual(created.status_code, 201, created.text)
        media_path = Path(self.directory.name) / "media" / f"{extraction['document_id']}.png"
        self.assertTrue(media_path.is_file())

        with closing(sqlite3.connect(Path(self.directory.name) / "forms.sqlite3")) as conn, conn:
            conn.execute("UPDATE sessions SET expires_at = '2000-01-01T00:00:00+00:00'")
        expired = self.client.post("/api/v1/sessions/heartbeat", headers=self.headers)
        self.assertEqual(expired.status_code, 401, expired.text)

        deleted = FormStore(self.settings).cleanup_expired_sessions()
        self.assertEqual(deleted, 1)
        self.assertFalse(media_path.exists())
        with closing(sqlite3.connect(Path(self.directory.name) / "forms.sqlite3")) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM forms").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM media").fetchone()[0], 0)

    def test_session_form_limit_is_enforced_per_session(self) -> None:
        self.settings.max_session_forms = 1
        first = self.extract()
        created = self.upload(first, self.values(first), "/api/v1/forms")
        self.assertEqual(created.status_code, 201, created.text)
        form_id = created.json()["id"]

        second = self.extract()
        rejected = self.upload(second, self.values(second), "/api/v1/forms")
        self.assertEqual(rejected.status_code, 409, rejected.text)
        self.assertIn("at most 1 saved forms", rejected.json()["detail"])
        self.assertFalse(
            (Path(self.directory.name) / "media" / f"{second['document_id']}.png").exists()
        )
        self.assertEqual(self.client.delete(
            f"/api/v1/forms/{form_id}", headers=self.headers
        ).status_code, 204)
        accepted_after_delete = self.upload(
            second, self.values(second), "/api/v1/forms"
        )
        self.assertEqual(accepted_after_delete.status_code, 201, accepted_after_delete.text)

        original_headers = self.headers
        self.headers = self.create_session_headers()
        try:
            other = self.extract()
            accepted = self.upload(other, self.values(other), "/api/v1/forms")
            self.assertEqual(accepted.status_code, 201, accepted.text)
        finally:
            self.headers = original_headers

    def test_session_storage_limit_allows_replace_but_rejects_add(self) -> None:
        self.settings.max_session_storage_bytes = len(self.png)
        first = self.extract()
        created = self.upload(first, self.values(first), "/api/v1/forms")
        self.assertEqual(created.status_code, 201, created.text)
        form_id = created.json()["id"]

        replacement = self.extract()
        replaced = self.upload(
            replacement, self.values(replacement),
            f"/api/v1/forms/{form_id}/media", "replace",
        )
        self.assertEqual(replaced.status_code, 200, replaced.text)

        extra = self.extract()
        rejected = self.upload(
            extra, self.values(extra), f"/api/v1/forms/{form_id}/media", "add"
        )
        self.assertEqual(rejected.status_code, 413, rejected.text)
        self.assertIn("can store at most", rejected.json()["detail"])
        self.assertFalse(
            (Path(self.directory.name) / "media" / f"{extra['document_id']}.png").exists()
        )
        self.assertEqual(self.client.delete(
            f"/api/v1/forms/{form_id}", headers=self.headers
        ).status_code, 204)
        accepted_after_delete = self.upload(extra, self.values(extra), "/api/v1/forms")
        self.assertEqual(accepted_after_delete.status_code, 201, accepted_after_delete.text)
        with closing(sqlite3.connect(Path(self.directory.name) / "forms.sqlite3")) as conn:
            stored_size, media_count = conn.execute(
                "SELECT COALESCE(SUM(size_bytes), 0), COUNT(*) FROM media"
            ).fetchone()
            self.assertEqual(stored_size, len(self.png))
            self.assertEqual(media_count, 1)

    def test_ocr_rate_limit_is_scoped_to_the_session(self) -> None:
        self.settings.max_ocr_requests_per_session_per_minute = 1
        self.settings.max_ocr_requests_per_minute = 100
        self.extract()

        rejected = self.client.post(
            "/api/v1/documents/extract",
            data={"form_type": "person"},
            files={"file": ("card.png", self.png, "image/png")},
            headers=self.headers,
        )
        self.assertEqual(rejected.status_code, 429, rejected.text)
        self.assertEqual(rejected.headers["retry-after"], "60")
        self.assertIn("Too many documents", rejected.json()["detail"])

        other_headers = self.create_session_headers()
        accepted = self.client.post(
            "/api/v1/documents/extract",
            data={"form_type": "person"},
            files={"file": ("card.png", self.png, "image/png")},
            headers=other_headers,
        )
        self.assertEqual(accepted.status_code, 200, accepted.text)

    def test_session_creation_rate_limit_returns_retry_after(self) -> None:
        self.settings.max_session_creations_per_minute = 1
        self.assertEqual(self.client.post("/api/v1/sessions").status_code, 201)

        rejected = self.client.post("/api/v1/sessions")
        self.assertEqual(rejected.status_code, 429, rejected.text)
        self.assertEqual(rejected.headers["retry-after"], "60")


if __name__ == "__main__":
    unittest.main()
