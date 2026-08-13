from app.connectors.google_drive.mock_client import _encode_content
from app.pipeline.extractors import UnsupportedMimeTypeError, get_extractor

BODY = "Title Paragraph\n\nThis is the second paragraph with some real content."


def test_plain_text_extractor():
    content = _encode_content(BODY, "text/plain")
    doc = get_extractor("text/plain").extract(content)
    assert "second paragraph" in doc.text
    assert doc.extracted_title == "Title Paragraph"


def test_html_extractor():
    content = _encode_content(BODY, "application/vnd.google-apps.document")
    doc = get_extractor("application/vnd.google-apps.document").extract(content)
    assert "second paragraph" in doc.text
    assert doc.extracted_title == "Title Paragraph"


def test_docx_extractor():
    mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    content = _encode_content(BODY, mime)
    doc = get_extractor(mime).extract(content)
    assert "second paragraph" in doc.text
    assert doc.extracted_title == "Title Paragraph"


def test_pdf_extractor():
    content = _encode_content(BODY, "application/pdf")
    doc = get_extractor("application/pdf").extract(content)
    assert "second paragraph" in doc.text.lower() or "second" in doc.text.lower()
    assert doc.text.strip() != ""


def test_unsupported_mime_type_raises():
    try:
        get_extractor("application/x-unknown")
        assert False, "expected UnsupportedMimeTypeError"
    except UnsupportedMimeTypeError:
        pass
