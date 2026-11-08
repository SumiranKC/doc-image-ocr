"""Decode uploads into bounded pages shared by OCR and document preview."""

import base64
from dataclasses import dataclass
from io import BytesIO

import pypdfium2 as pdfium
from fastapi import HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError

from app.schemas import PagePreview


MIME_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
}
MAX_PAGE_PIXELS = 16_000_000
RENDER_WIDTH = 1600


@dataclass
class PreparedDocument:
    images: list[Image.Image]
    previews: list[PagePreview]


def prepare_document(
    content: bytes, mime_type: str, max_pdf_pages: int, include_previews: bool = True
) -> PreparedDocument:
    if mime_type not in MIME_EXTENSIONS:
        raise HTTPException(415, "Upload a JPEG, PNG, WebP, or PDF document.")
    try:
        if mime_type == "application/pdf":
            if not content.startswith(b"%PDF-"):
                raise ValueError("Invalid PDF")
            pdf = pdfium.PdfDocument(content)
            try:
                if len(pdf) < 1 or len(pdf) > max_pdf_pages:
                    raise HTTPException(413, f"PDF must contain 1 to {max_pdf_pages} pages.")
                images = [render_pdf_page(pdf, index) for index in range(len(pdf))]
            finally:
                pdf.close()
            previews = []
            for index, image in enumerate(images):
                data_url = None
                if include_previews:
                    buffer = BytesIO()
                    image.save(buffer, format="PNG")
                    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
                    data_url = f"data:image/png;base64,{encoded}"
                previews.append(PagePreview(
                    index=index, width=image.width, height=image.height,
                    data_url=data_url,
                ))
            return PreparedDocument(images, previews)

        with Image.open(BytesIO(content)) as source:
            expected = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}[mime_type]
            if source.format != expected or source.width * source.height > MAX_PAGE_PIXELS:
                raise ValueError("Invalid or oversized image")
            image = ImageOps.exif_transpose(source).convert("RGB")
        image.thumbnail((RENDER_WIDTH, RENDER_WIDTH), Image.Resampling.LANCZOS)
        return PreparedDocument(
            [image], [PagePreview(index=0, width=image.width, height=image.height)]
        )
    except HTTPException:
        raise
    except (ValueError, UnidentifiedImageError, OSError, pdfium.PdfiumError) as exc:
        raise HTTPException(422, "The uploaded document could not be read.") from exc


def render_pdf_page(pdf: pdfium.PdfDocument, index: int) -> Image.Image:
    page = pdf[index]
    try:
        width, height = page.get_size()
        scale = min(2.0, RENDER_WIDTH / max(width, height))
        if width * height * scale * scale > MAX_PAGE_PIXELS:
            raise ValueError("PDF page is too large")
        return page.render(scale=scale).to_pil().convert("RGB")
    finally:
        page.close()
