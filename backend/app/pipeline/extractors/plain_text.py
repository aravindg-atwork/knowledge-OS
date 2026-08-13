from app.pipeline.extractors.base import ContentExtractor, ExtractedDoc


class PlainTextExtractor(ContentExtractor):
    def extract(self, content: bytes) -> ExtractedDoc:
        text = content.decode("utf-8", errors="replace")
        first_line = text.strip().splitlines()[0] if text.strip() else None
        return ExtractedDoc(text=text, extracted_title=first_line)
