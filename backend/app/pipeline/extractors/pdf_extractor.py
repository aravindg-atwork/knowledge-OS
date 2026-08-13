import io

from pypdf import PdfReader

from app.pipeline.extractors.base import ContentExtractor, ExtractedDoc


class PdfExtractor(ContentExtractor):
    """Handles both text-layer PDFs. Scanned/image-only PDFs (no text layer)
    would need an OCR step upstream -- out of scope for this milestone."""

    def extract(self, content: bytes) -> ExtractedDoc:
        reader = PdfReader(io.BytesIO(content))
        pages_text = [page.extract_text() or "" for page in reader.pages]
        text = "\n\n".join(t for t in pages_text if t.strip())
        metadata = reader.metadata or {}
        extracted_title = metadata.get("/Title") or (text.splitlines()[0] if text else None)
        author = metadata.get("/Author") or None
        return ExtractedDoc(text=text, extracted_title=extracted_title, author=author)
