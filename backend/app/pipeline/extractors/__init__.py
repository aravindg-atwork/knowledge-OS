from app.pipeline.extractors.base import ContentExtractor, ExtractedDoc, UnsupportedMimeTypeError
from app.pipeline.extractors.docx_extractor import DocxExtractor
from app.pipeline.extractors.html_extractor import HtmlExtractor
from app.pipeline.extractors.pdf_extractor import PdfExtractor
from app.pipeline.extractors.plain_text import PlainTextExtractor

_EXTRACTORS_BY_MIME: dict[str, ContentExtractor] = {
    "text/plain": PlainTextExtractor(),
    "text/markdown": PlainTextExtractor(),
    "text/html": HtmlExtractor(),
    "application/vnd.google-apps.document": HtmlExtractor(),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": DocxExtractor(),
    "application/msword": DocxExtractor(),
    "application/pdf": PdfExtractor(),
}


def get_extractor(mime_type: str) -> ContentExtractor:
    try:
        return _EXTRACTORS_BY_MIME[mime_type]
    except KeyError as exc:
        raise UnsupportedMimeTypeError(
            f"No extractor registered for mime type: {mime_type}"
        ) from exc


__all__ = ["ExtractedDoc", "UnsupportedMimeTypeError", "get_extractor"]
