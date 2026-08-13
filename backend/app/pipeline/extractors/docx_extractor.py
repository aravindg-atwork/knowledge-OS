import io

import docx

from app.pipeline.extractors.base import ContentExtractor, ExtractedDoc


class DocxExtractor(ContentExtractor):
    def extract(self, content: bytes) -> ExtractedDoc:
        document = docx.Document(io.BytesIO(content))
        paragraphs = [p.text for p in document.paragraphs if p.text.strip()]
        text = "\n\n".join(paragraphs)
        core_props = document.core_properties
        extracted_title = core_props.title or (paragraphs[0] if paragraphs else None)
        author = core_props.author or None
        return ExtractedDoc(text=text, extracted_title=extracted_title, author=author)
