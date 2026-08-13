from bs4 import BeautifulSoup

from app.pipeline.extractors.base import ContentExtractor, ExtractedDoc


class HtmlExtractor(ContentExtractor):
    """Handles Google Docs-style content, exported/mocked as HTML."""

    def extract(self, content: bytes) -> ExtractedDoc:
        soup = BeautifulSoup(content.decode("utf-8", errors="replace"), "html.parser")
        paragraphs = [p.get_text(strip=True) for p in soup.find_all("p")]
        text = "\n\n".join(p for p in paragraphs if p)
        title_tag = soup.find("title")
        first_paragraph = paragraphs[0] if paragraphs else None
        extracted_title = title_tag.get_text(strip=True) if title_tag else first_paragraph
        return ExtractedDoc(text=text, extracted_title=extracted_title)
