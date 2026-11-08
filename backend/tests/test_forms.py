import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings, get_settings
from app.main import app, get_ocr_engine
from app.schemas import FORM_FIELDS, Point, TextBlock


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
        app.dependency_overrides[get_settings] = lambda: Settings(data_dir=Path(self.directory.name))
        app.dependency_overrides[get_ocr_engine] = FakeOCREngine
        self.client = TestClient(app)
        buffer = BytesIO()
        Image.new("RGB", (300, 160), "white").save(buffer, format="PNG")
        self.png = buffer.getvalue()

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.client.close()
        self.directory.cleanup()

    def extract(self, content: bytes | None = None, mime: str = "image/png", filename: str = "card.png") -> dict:
        response = self.client.post(
            "/api/v1/documents/extract",
            data={"form_type": "person"},
            files={"file": (filename, content or self.png, mime)},
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
        return self.client.post(path, data=data, files={"file": (filename, content or self.png, mime)})

    def test_create_edit_add_replace_delete(self) -> None:
        first = self.extract()
        created = self.upload(first, self.values(first), "/api/v1/forms")
        self.assertEqual(created.status_code, 201, created.text)
        form = created.json()
        form_id = form["id"]
        first_path = Path(self.directory.name) / "media" / f"{first['document_id']}.png"
        self.assertTrue(first_path.is_file())
        self.assertEqual(form["fields"]["full_name"]["value"], "Alice Example")
        self.assertEqual(len(self.client.get("/api/v1/forms").json()), 1)

        edited = form["fields"]
        edited["job_title"]["value"] = "Director"
        edited["job_title"]["edited"] = True
        response = self.client.put(f"/api/v1/forms/{form_id}", json={"fields": edited})
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
        self.assertEqual(self.client.get(f"/api/v1/forms/{form_id}/media/{first['document_id']}").status_code, 404)
        self.assertEqual(self.client.get(f"/api/v1/forms/{form_id}/media/{replacement['document_id']}/pages/0").status_code, 200)

        self.assertEqual(self.client.delete(f"/api/v1/forms/{form_id}").status_code, 204)
        self.assertEqual(self.client.get(f"/api/v1/forms/{form_id}").status_code, 404)
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
        preview = self.client.get(f"/api/v1/forms/{record['id']}/media/{extraction['document_id']}/pages/1")
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertEqual(preview.headers["content-type"], "image/png")
        self.assertEqual(preview.content[:8], b"\x89PNG\r\n\x1a\n")

    def test_organization_form_uses_its_own_fields(self) -> None:
        app.dependency_overrides[get_ocr_engine] = FakeOrganizationOCR
        extracted = self.client.post(
            "/api/v1/documents/extract", data={"form_type": "organization"},
            files={"file": ("company.png", self.png, "image/png")},
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
        )
        self.assertEqual(saved.status_code, 201, saved.text)
        self.assertEqual(saved.json()["display_name"], "Example Studio")


if __name__ == "__main__":
    unittest.main()
