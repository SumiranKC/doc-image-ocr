from typing import Protocol

import numpy as np
from PIL import Image

from app.schemas import Point, TextBlock


class OCREngine(Protocol):
    def recognize(self, images: list[Image.Image]) -> list[TextBlock]: ...


class PaddleOCREngine:
    """PaddleOCR adapter; no Paddle-specific data leaves this class."""

    def __init__(self) -> None:
        from paddleocr import PaddleOCR

        self._client = PaddleOCR(
            lang="en",
            enable_mkldnn=False,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )

    def recognize(self, images: list[Image.Image]) -> list[TextBlock]:
        blocks: list[TextBlock] = []
        for page_index, image in enumerate(images):
            for page in self._client.predict(np.asarray(image)):
                for text, confidence, box in zip(
                    page["rec_texts"], page["rec_scores"], page["rec_polys"], strict=True
                ):
                    if not str(text).strip() or float(confidence) < 0.5:
                        continue
                    blocks.append(
                        TextBlock(
                            text=str(text),
                            confidence=float(confidence),
                            bounding_box=[Point(x=float(x), y=float(y)) for x, y in box],
                            page_index=page_index,
                        )
                    )
        return blocks
