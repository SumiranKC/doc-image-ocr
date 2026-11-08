import re

from app.schemas import ExtractedField, FormType, TextBlock


LABELS = {
    "full_name": "Full name", "title": "Title", "job_title": "Job title",
    "organization": "Organization", "organization_name": "Organization name",
    "email": "Email", "phone": "Phone", "website": "Website",
    "address": "Address", "notes": "Notes", "description": "Description",
}

EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
PHONE = re.compile(r"(?<!\w)(?:\+?\d[\d ()-]{7,}\d)(?!\w)")
WEBSITE = re.compile(r"\b(?:https?://)?(?:www\.)?[a-z\d-]+(?:\.[a-z\d-]+)+\b(?:/[^\s]*)?", re.I)
FIELD_PATTERNS = {
    "full_name": re.compile(r"^(?:full\s*name|contact\s*person|name)\s*[:\-]\s*(.+)$", re.I),
    "title": re.compile(r"^(?:title|salutation)\s*[:\-]\s*(.+)$", re.I),
    "job_title": re.compile(r"^(?:job\s*title|position|role)\s*[:\-]\s*(.+)$", re.I),
    "organization": re.compile(r"^(?:organization|organisation|company)\s*[:\-]\s*(.+)$", re.I),
    "organization_name": re.compile(r"^(?:organization|organisation|company|business)\s*(?:name)?\s*[:\-]\s*(.+)$", re.I),
    "address": re.compile(r"^(?:address|street\s*address)\s*[:\-]\s*(.+)$", re.I),
    "notes": re.compile(r"^(?:notes?)\s*[:\-]\s*(.+)$", re.I),
    "description": re.compile(r"^(?:description|about)\s*[:\-]\s*(.+)$", re.I),
}


def extract_fields(blocks: list[TextBlock], form_type: FormType, media_id: str) -> list[ExtractedField]:
    """Return conservative suggestions and the block behind each value."""
    values: dict[str, ExtractedField] = {}
    for index, block in enumerate(blocks):
        text = block.text.strip()
        for key, pattern in (("email", EMAIL), ("phone", PHONE), ("website", WEBSITE)):
            if key in values:
                continue
            match = pattern.search(text)
            if match and (key != "website" or "@" not in text):
                values[key] = _field(key, match.group().strip(), block, media_id, index)
        for key, pattern in FIELD_PATTERNS.items():
            if key in values or (form_type == "person" and key in {"organization_name", "description"}) or (form_type == "organization" and key in {"full_name", "title", "job_title", "organization", "notes"}):
                continue
            match = pattern.match(text)
            if match:
                values[key] = _field(key, match.group(1).strip(), block, media_id, index)
    allowed = ("full_name", "title", "job_title", "organization", "email", "phone", "website", "address", "notes") if form_type == "person" else ("organization_name", "email", "phone", "website", "address", "description")
    return [values[key] for key in allowed if key in values]


def _field(key: str, value: str, block: TextBlock, media_id: str, index: int) -> ExtractedField:
    return ExtractedField(
        key=key, label=LABELS[key], value=value,
        confidence=block.confidence, source_media_id=media_id, source_block_index=index,
    )
