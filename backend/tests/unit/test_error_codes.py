import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.errors import (
    AppError,
    ConflictError,
    EmailNotVerifiedError,
    InvalidTokenError,
    TokenExpiredError,
    register_exception_handlers,
)


def test_app_error_carries_code():
    err = AppError("boom", code="some_code")
    assert err.code == "some_code"


def test_app_error_code_defaults_to_none():
    assert AppError("boom").code is None


def test_new_error_classes_have_expected_status_and_code():
    assert (EmailNotVerifiedError().status_code, EmailNotVerifiedError().code) == (
        403,
        "email_not_verified",
    )
    assert (InvalidTokenError().status_code, InvalidTokenError().code) == (400, "invalid_token")
    assert (TokenExpiredError().status_code, TokenExpiredError().code) == (400, "token_expired")


def test_conflict_error_accepts_explicit_code():
    err = ConflictError("already there", code="already_member")
    assert (err.status_code, err.code) == (409, "already_member")


def test_handler_serialises_code_in_body():
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    def boom():
        raise EmailNotVerifiedError()

    resp = TestClient(app, raise_server_exceptions=False).get("/boom")
    assert resp.status_code == 403
    assert resp.json()["code"] == "email_not_verified"


def test_handler_omits_code_when_absent():
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    def boom():
        raise AppError("plain")

    resp = TestClient(app, raise_server_exceptions=False).get("/boom")
    assert resp.json()["code"] is None
