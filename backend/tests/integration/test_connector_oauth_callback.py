def test_oauth_callback_escapes_error_query_param(client):
    """FIX 7: the `error` query parameter on the Google OAuth callback is
    attacker-controlled (anyone can craft a link to this endpoint with any
    `error` value) and was being reflected straight into unescaped HTML --
    reflected XSS on the API origin. It must come back HTML-escaped."""
    resp = client.get(
        "/api/v1/connectors/google/oauth/callback",
        params={"error": "<script>alert(document.cookie)</script>"},
    )
    assert resp.status_code == 200
    assert "<script>" not in resp.text
    assert "&lt;script&gt;" in resp.text


def test_oauth_callback_still_shows_plain_error_reason(client):
    """The escaping fix must not make ordinary (non-malicious) error
    reasons unreadable."""
    resp = client.get(
        "/api/v1/connectors/google/oauth/callback",
        params={"error": "access_denied"},
    )
    assert resp.status_code == 200
    assert "access_denied" in resp.text
