# Tenancy & Onboarding (1a) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a stranger sign up, verify their email, land in their own workspace, invite teammates, and have `admin` vs `member` actually enforced.

**Architecture:** Login keeps carrying a single `workspace_id` inside the JWT, so every existing workspace-scoped endpoint (documents, chat, retrieval, Qdrant filtering) stays untouched; switching workspaces mints a new token. Email delivery mirrors the existing swappable-provider pattern in `app/ai/`, defaulting to a console provider so local dev needs no credentials. All emailed tokens are stored SHA-256 hashed.

**Tech Stack:** FastAPI, SQLAlchemy 2.x (`Mapped`/`mapped_column`), Alembic, PostgreSQL, Redis, pydantic-settings, passlib/bcrypt, PyJWT, pytest, React 18 + TypeScript + react-router-dom, Tailwind.

**Spec:** `docs/superpowers/specs/2026-08-15-tenancy-onboarding-design.md`

## Global Constraints

- Python target matches `backend/Dockerfile` (`python:3.11-slim`). Do not introduce 3.12+ syntax.
- Role set stays exactly `admin` | `member`. Do **not** add roles — Qdrant payloads written at `workers/tasks_ingestion.py:63` carry these two values and any change forces a re-index.
- Emailed tokens are stored **hashed (SHA-256)**, never plaintext. The raw token appears only in the email link.
- Timestamps are timezone-aware UTC: `datetime.now(UTC)`, columns `DateTime(timezone=True)`.
- Follow the existing error convention: raise `AppError` subclasses from `app/core/errors.py`. Do not raise bare `HTTPException` in new code.
- All new endpoints that mutate state call `log_audit_event(...)` from `app/core/audit.py`, matching the `auth.login.success` / `auth.login.failure` naming style.
- `EMAIL_PROVIDER` defaults to `console`. `docker compose up` must keep working with **zero** email credentials.
- Alembic revisions continue the existing linear chain. Current head is `0003`.
- Tests live in `backend/tests/unit/` and `backend/tests/integration/`, following existing file naming (`test_<behavior>.py`).
- `seed_dev_data.py` stays in the tree until Task 17. It is currently the only way a user exists.

---

## File Structure

**Backend — created:**

| File | Responsibility |
|---|---|
| `app/email/provider.py` | `EmailProvider` protocol + `EmailMessage` dataclass |
| `app/email/console.py` | Dev provider: logs the message and any link |
| `app/email/resend_provider.py` | Production provider via Resend HTTP API |
| `app/email/factory.py` | `get_email_provider()` selecting on `EMAIL_PROVIDER` |
| `app/email/templates.py` | Pure functions returning `EmailMessage` per email type |
| `app/services/token_service.py` | Generate / hash / consume single-use tokens |
| `app/services/tenancy_service.py` | Workspace creation, slug generation, membership mutation |
| `app/services/invitation_service.py` | Issue, preview, accept, revoke invites |
| `app/api/v1/workspaces.py` | Workspace + member endpoints |
| `app/api/v1/invitations.py` | Invitation endpoints |
| `app/models/auth_token.py` | `AuthToken` model + `AuthTokenPurpose` enum |
| `app/models/invitation.py` | `Invitation` model |
| `alembic/versions/0004_tenancy_onboarding.py` | Migration |

**Backend — modified:**

| File | Change |
|---|---|
| `app/core/errors.py` | Add `code` to `AppError`; add 4 error classes |
| `app/core/config.py` | Add email + frontend URL + rate-limit settings |
| `app/models/user.py` | Add `email_verified_at`, `full_name` |
| `app/api/deps.py` | Membership re-check, `require_admin`, verified-email gate |
| `app/api/v1/auth.py` | Signup, verification, reset, switch-workspace, `/me` |
| `app/api/v1/router.py` | Register the two new routers |
| `app/repositories/workspace_repository.py` | Membership listing helpers |

**Frontend — created:** `features/auth/SignupPage.tsx`, `VerifyEmailPage.tsx`, `ForgotPasswordPage.tsx`, `ResetPasswordPage.tsx`, `features/invites/AcceptInvitePage.tsx`, `features/settings/WorkspaceSettingsPage.tsx`, `features/settings/MembersPage.tsx`, `app/AuthContext.tsx`, `app/guards.tsx`, `components/WorkspaceSwitcher.tsx`.

**Frontend — modified:** `app/routes.tsx` (guards + new routes), `app/AppShell.tsx` (switcher + settings nav), `lib/apiClient.ts` (error `code` propagation).

---

### Task 1: Error codes foundation

Everything downstream needs machine-readable error codes; the frontend must tell "email not verified" from an ordinary 403.

**Files:**
- Modify: `backend/app/core/errors.py`
- Test: `backend/tests/unit/test_error_codes.py`

**Interfaces:**
- Consumes: nothing
- Produces: `AppError(message, code=None)` with `.code`; `EmailNotVerifiedError`, `InvalidTokenError`, `TokenExpiredError` classes; JSON body `{"detail": str, "code": str | None}`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_error_codes.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/test_error_codes.py -v`
Expected: FAIL — `ImportError: cannot import name 'EmailNotVerifiedError'`

- [ ] **Step 3: Write minimal implementation**

Open `backend/app/core/errors.py`. Give `AppError` a `code`, keeping the existing positional `message` signature so no current call site breaks:

```python
class AppError(Exception):
    status_code = 500
    code: str | None = None

    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
```

Add the new classes beside the existing ones:

```python
class EmailNotVerifiedError(AppError):
    status_code = 403
    code = "email_not_verified"

    def __init__(self, message: str = "Email address not verified", code: str | None = None) -> None:
        super().__init__(message, code)


class InvalidTokenError(AppError):
    status_code = 400
    code = "invalid_token"

    def __init__(self, message: str = "Invalid token", code: str | None = None) -> None:
        super().__init__(message, code)


class TokenExpiredError(AppError):
    status_code = 400
    code = "token_expired"

    def __init__(self, message: str = "Token has expired", code: str | None = None) -> None:
        super().__init__(message, code)
```

In the handler, add `code` to the response body:

```python
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.message, "code": exc.code},
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/unit/test_error_codes.py tests/unit/test_error_handling.py -v`
Expected: PASS — including the pre-existing `test_error_handling.py`, which must not regress.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/errors.py backend/tests/unit/test_error_codes.py
git commit -m "feat: add machine-readable error codes to AppError"
```

---

### Task 2: Email provider abstraction

**Files:**
- Create: `backend/app/email/__init__.py`, `provider.py`, `console.py`, `resend_provider.py`, `factory.py`, `templates.py`
- Modify: `backend/app/core/config.py`, `backend/requirements.txt`, `.env.example`
- Test: `backend/tests/unit/test_email_provider.py`

**Interfaces:**
- Consumes: nothing
- Produces: `EmailMessage(to: str, subject: str, text: str, html: str)`; `EmailProvider.send(message: EmailMessage) -> None`; `get_email_provider() -> EmailProvider`; `FakeEmailProvider` with `.sent: list[EmailMessage]`; template functions `verify_email_message(to, link)`, `invite_message(to, workspace_name, inviter_email, link)`, `password_reset_message(to, link)` — each returning `EmailMessage`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_email_provider.py
import pytest

from app.email.console import ConsoleEmailProvider
from app.email.factory import get_email_provider
from app.email.provider import EmailMessage, FakeEmailProvider
from app.email.templates import (
    invite_message,
    password_reset_message,
    verify_email_message,
)


def test_fake_provider_records_sends():
    provider = FakeEmailProvider()
    msg = EmailMessage(to="a@b.com", subject="Hi", text="body", html="<p>body</p>")
    provider.send(msg)
    assert provider.sent == [msg]


def test_console_provider_logs_without_raising(caplog):
    ConsoleEmailProvider().send(
        EmailMessage(to="a@b.com", subject="Hi", text="click http://x/y", html="<p>x</p>")
    )
    assert "a@b.com" in caplog.text


def test_factory_returns_console_by_default(monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "console")
    get_email_provider.cache_clear()
    assert isinstance(get_email_provider(), ConsoleEmailProvider)


def test_factory_rejects_unknown_provider(monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "carrier-pigeon")
    get_email_provider.cache_clear()
    with pytest.raises(ValueError, match="carrier-pigeon"):
        get_email_provider()


def test_templates_embed_the_link_in_both_parts():
    link = "https://app.test/verify?token=abc123"
    for msg in (
        verify_email_message("a@b.com", link),
        password_reset_message("a@b.com", link),
        invite_message("a@b.com", "Acme Corp", "boss@acme.com", link),
    ):
        assert link in msg.text
        assert link in msg.html
        assert msg.to == "a@b.com"
        assert msg.subject


def test_invite_template_names_the_workspace_and_inviter():
    msg = invite_message("a@b.com", "Acme Corp", "boss@acme.com", "https://x/y")
    assert "Acme Corp" in msg.text
    assert "boss@acme.com" in msg.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/test_email_provider.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.email'`

- [ ] **Step 3: Write minimal implementation**

`backend/app/email/__init__.py` — empty file.

`backend/app/email/provider.py`:

```python
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    text: str
    html: str


class EmailProvider(Protocol):
    def send(self, message: EmailMessage) -> None: ...


@dataclass
class FakeEmailProvider:
    """Test double. Records sends so tests can assert on real link tokens
    instead of mocking at the transport layer."""

    sent: list[EmailMessage] = field(default_factory=list)

    def send(self, message: EmailMessage) -> None:
        self.sent.append(message)
```

`backend/app/email/console.py`:

```python
import logging

from app.email.provider import EmailMessage

logger = logging.getLogger(__name__)


class ConsoleEmailProvider:
    """Dev provider: prints the email instead of sending it, so local
    development needs no email credentials. Links are readable in
    `docker compose logs backend`."""

    def send(self, message: EmailMessage) -> None:
        logger.info(
            "email.console.send",
            extra={"to": message.to, "subject": message.subject},
        )
        logger.info("--- EMAIL TO %s: %s ---\n%s", message.to, message.subject, message.text)
```

`backend/app/email/resend_provider.py`:

```python
import httpx

from app.core.errors import TransientConnectorError
from app.email.provider import EmailMessage

_RESEND_ENDPOINT = "https://api.resend.com/emails"


class ResendEmailProvider:
    def __init__(self, api_key: str, from_address: str) -> None:
        self._api_key = api_key
        self._from_address = from_address

    def send(self, message: EmailMessage) -> None:
        try:
            response = httpx.post(
                _RESEND_ENDPOINT,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "from": self._from_address,
                    "to": [message.to],
                    "subject": message.subject,
                    "text": message.text,
                    "html": message.html,
                },
                timeout=10.0,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise TransientConnectorError(f"Resend send failed: {exc}") from exc
```

`backend/app/email/factory.py`:

```python
from functools import lru_cache

from app.core.config import get_settings
from app.email.console import ConsoleEmailProvider
from app.email.provider import EmailProvider
from app.email.resend_provider import ResendEmailProvider


@lru_cache(maxsize=1)
def get_email_provider() -> EmailProvider:
    settings = get_settings()
    provider = settings.EMAIL_PROVIDER.lower()
    if provider == "console":
        return ConsoleEmailProvider()
    if provider == "resend":
        if not settings.RESEND_API_KEY:
            raise ValueError("EMAIL_PROVIDER=resend requires RESEND_API_KEY")
        return ResendEmailProvider(settings.RESEND_API_KEY, settings.EMAIL_FROM_ADDRESS)
    raise ValueError(f"Unknown EMAIL_PROVIDER: {provider}")
```

`backend/app/email/templates.py`:

```python
from app.email.provider import EmailMessage

_PRODUCT = "Enterprise Knowledge Hub"


def verify_email_message(to: str, link: str) -> EmailMessage:
    text = (
        f"Welcome to {_PRODUCT}.\n\n"
        f"Confirm this address to activate your workspace:\n{link}\n\n"
        "This link expires in 7 days. If you didn't sign up, ignore this email."
    )
    html = (
        f"<p>Welcome to {_PRODUCT}.</p>"
        f'<p><a href="{link}">Confirm your email address</a></p>'
        f"<p>Or paste this link: {link}</p>"
        "<p>This link expires in 7 days. If you didn't sign up, ignore this email.</p>"
    )
    return EmailMessage(to=to, subject=f"Confirm your {_PRODUCT} email", text=text, html=html)


def password_reset_message(to: str, link: str) -> EmailMessage:
    text = (
        f"A password reset was requested for your {_PRODUCT} account.\n\n"
        f"Reset it here:\n{link}\n\n"
        "This link expires in 1 hour. If you didn't request it, ignore this email."
    )
    html = (
        f"<p>A password reset was requested for your {_PRODUCT} account.</p>"
        f'<p><a href="{link}">Reset your password</a></p>'
        f"<p>Or paste this link: {link}</p>"
        "<p>This link expires in 1 hour. If you didn't request it, ignore this email.</p>"
    )
    return EmailMessage(to=to, subject=f"Reset your {_PRODUCT} password", text=text, html=html)


def invite_message(to: str, workspace_name: str, inviter_email: str, link: str) -> EmailMessage:
    text = (
        f"{inviter_email} invited you to the {workspace_name} workspace "
        f"on {_PRODUCT}.\n\nAccept the invitation:\n{link}\n\n"
        "This invitation expires in 7 days."
    )
    html = (
        f"<p>{inviter_email} invited you to the <strong>{workspace_name}</strong> "
        f"workspace on {_PRODUCT}.</p>"
        f'<p><a href="{link}">Accept the invitation</a></p>'
        f"<p>Or paste this link: {link}</p>"
        "<p>This invitation expires in 7 days.</p>"
    )
    return EmailMessage(to=to, subject=f"Join {workspace_name} on {_PRODUCT}", text=text, html=html)
```

In `backend/app/core/config.py`, add to `Settings` beside the existing `AI_PROVIDER` block:

```python
    # Email -- console prints to logs so local dev needs no credentials.
    EMAIL_PROVIDER: str = "console"  # console | resend
    RESEND_API_KEY: str = ""
    EMAIL_FROM_ADDRESS: str = "no-reply@localhost"
    # Base URL the emailed links point at (the frontend, not the API).
    FRONTEND_BASE_URL: str = "http://localhost:5173"
    RATE_LIMIT_SIGNUP: str = "5/hour"
    RATE_LIMIT_INVITE: str = "30/hour"
    RATE_LIMIT_PASSWORD_RESET: str = "5/hour"
```

Add to `backend/requirements.txt`:

```
email-validator==2.2.0
```

**This is required, not optional.** Tasks 6, 8, and 11 use `pydantic.EmailStr`, which raises at import time without it. Verified absent from the running container during pre-flight. `httpx==0.27.2` and `redis==5.0.8` are already present — do not re-add them.

After editing requirements, rebuild so the container has the package:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build backend celery_worker celery_beat
```

Mirror the new settings into `.env.example` with the same defaults.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/unit/test_email_provider.py tests/unit/test_config_validation.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/email backend/app/core/config.py backend/requirements.txt .env.example backend/tests/unit/test_email_provider.py
git commit -m "feat: add swappable email provider with console default"
```

---

### Task 3: Data model and migration 0004

**Files:**
- Create: `backend/app/models/auth_token.py`, `backend/app/models/invitation.py`, `backend/alembic/versions/0004_tenancy_onboarding.py`
- Modify: `backend/app/models/user.py`, `backend/app/models/__init__.py`
- Test: `backend/tests/integration/test_tenancy_models.py`

**Interfaces:**
- Consumes: nothing
- Produces: `AuthToken(id, user_id, purpose, token_hash, expires_at, used_at)`; `AuthTokenPurpose.verify_email | .password_reset`; `Invitation(id, workspace_id, email, role, token_hash, invited_by_user_id, expires_at, accepted_at)`; `User.email_verified_at`, `User.full_name`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/test_tenancy_models.py
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.auth_token import AuthToken, AuthTokenPurpose
from app.models.invitation import Invitation
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceRole


def _workspace(db) -> Workspace:
    ws = Workspace(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}")
    db.add(ws)
    db.flush()
    return ws


def test_user_defaults_to_unverified(db):
    user = User(email=f"u-{uuid.uuid4().hex[:8]}@t.local", hashed_password="x")
    db.add(user)
    db.flush()
    assert user.email_verified_at is None
    assert user.full_name is None


def test_auth_token_roundtrips(db):
    user = User(email=f"u-{uuid.uuid4().hex[:8]}@t.local", hashed_password="x")
    db.add(user)
    db.flush()
    token = AuthToken(
        user_id=user.id,
        purpose=AuthTokenPurpose.verify_email,
        token_hash="deadbeef",
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db.add(token)
    db.flush()
    assert token.used_at is None


def test_pending_invite_is_unique_per_workspace_and_email(db):
    ws = _workspace(db)
    for _ in range(2):
        db.add(
            Invitation(
                workspace_id=ws.id,
                email="dup@acme.com",
                role=WorkspaceRole.member,
                token_hash=uuid.uuid4().hex,
                expires_at=datetime.now(UTC) + timedelta(days=7),
            )
        )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_accepted_invite_does_not_block_reinvite(db):
    ws = _workspace(db)
    db.add(
        Invitation(
            workspace_id=ws.id,
            email="returning@acme.com",
            role=WorkspaceRole.member,
            token_hash=uuid.uuid4().hex,
            expires_at=datetime.now(UTC) + timedelta(days=7),
            accepted_at=datetime.now(UTC),
        )
    )
    db.flush()
    db.add(
        Invitation(
            workspace_id=ws.id,
            email="returning@acme.com",
            role=WorkspaceRole.member,
            token_hash=uuid.uuid4().hex,
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
    )
    db.flush()  # must not raise -- the unique index is partial
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/integration/test_tenancy_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.models.auth_token'`

- [ ] **Step 3: Write minimal implementation**

`backend/app/models/auth_token.py`:

```python
import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, new_uuid


class AuthTokenPurpose(str, enum.Enum):
    verify_email = "verify_email"
    password_reset = "password_reset"


class AuthToken(Base, TimestampMixin):
    __tablename__ = "auth_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    purpose: Mapped[AuthTokenPurpose] = mapped_column(
        Enum(AuthTokenPurpose, name="auth_token_purpose"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

> Check `app/models/base.py` for the exact names of `Base`, `TimestampMixin`, and `new_uuid` before writing — mirror whatever `app/models/workspace.py` imports.

`backend/app/models/invitation.py`:

```python
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, new_uuid
from app.models.workspace import WorkspaceRole


class Invitation(Base, TimestampMixin):
    __tablename__ = "invitations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    role: Mapped[WorkspaceRole] = mapped_column(
        Enum(WorkspaceRole, name="workspace_role", create_type=False), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    invited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

In `backend/app/models/user.py` add:

```python
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

Import both new models in `backend/app/models/__init__.py` so Alembic autogenerate and `Base.metadata` see them.

Migration `backend/alembic/versions/0004_tenancy_onboarding.py`:

```python
"""tenancy: auth tokens, invitations, user verification fields

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("full_name", sa.String(length=255), nullable=True))
    op.add_column(
        "users", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True)
    )

    auth_token_purpose = postgresql.ENUM(
        "verify_email", "password_reset", name="auth_token_purpose"
    )
    auth_token_purpose.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "auth_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("purpose", auth_token_purpose, nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_auth_tokens_user_id", "auth_tokens", ["user_id"])
    op.create_index("ix_auth_tokens_token_hash", "auth_tokens", ["token_hash"])

    op.create_table(
        "invitations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM("admin", "member", name="workspace_role", create_type=False),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column(
            "invited_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_invitations_workspace_id", "invitations", ["workspace_id"])
    op.create_index("ix_invitations_email", "invitations", ["email"])
    op.create_index("ix_invitations_token_hash", "invitations", ["token_hash"])
    # Partial: no duplicate *pending* invites, but re-inviting someone who
    # left is allowed.
    op.create_index(
        "uq_invitations_pending_workspace_email",
        "invitations",
        ["workspace_id", "email"],
        unique=True,
        postgresql_where=sa.text("accepted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("invitations")
    op.drop_table("auth_tokens")
    postgresql.ENUM(name="auth_token_purpose").drop(op.get_bind(), checkfirst=True)
    op.drop_column("users", "email_verified_at")
    op.drop_column("users", "full_name")
```

- [ ] **Step 4: Apply the migration and run tests**

Run:
```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec -T backend alembic upgrade head
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec -T backend pytest tests/integration/test_tenancy_models.py -v
```
Expected: migration reports `0003 -> 0004`; tests PASS.

- [ ] **Step 5: Verify the downgrade path works**

Run:
```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec -T backend alembic downgrade 0003
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec -T backend alembic upgrade head
```
Expected: both succeed. A migration that cannot roll back is a liability in production.

- [ ] **Step 6: Commit**

```bash
git add backend/app/models backend/alembic/versions/0004_tenancy_onboarding.py backend/tests/integration/test_tenancy_models.py
git commit -m "feat: add auth_tokens and invitations tables with user verification fields"
```

---

### Task 4: Token service

Single-use, hashed, expiring tokens — shared by email verification, password reset, and invitations.

**Files:**
- Create: `backend/app/services/token_service.py`
- Test: `backend/tests/unit/test_token_service.py`

**Interfaces:**
- Consumes: nothing
- Produces: `generate_token() -> str` (URL-safe raw token); `hash_token(raw: str) -> str` (64-char SHA-256 hex); `is_expired(expires_at: datetime) -> bool`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_token_service.py
from datetime import UTC, datetime, timedelta

from app.services.token_service import generate_token, hash_token, is_expired


def test_generated_tokens_are_unique_and_urlsafe():
    tokens = {generate_token() for _ in range(100)}
    assert len(tokens) == 100
    for token in tokens:
        assert token.isascii()
        assert "/" not in token and "+" not in token and "=" not in token
        assert len(token) >= 32


def test_hash_is_stable_and_64_hex_chars():
    raw = generate_token()
    assert hash_token(raw) == hash_token(raw)
    assert len(hash_token(raw)) == 64
    int(hash_token(raw), 16)  # raises if not hex


def test_hash_differs_for_different_tokens():
    assert hash_token(generate_token()) != hash_token(generate_token())


def test_hash_is_not_reversible_to_the_raw_token():
    raw = generate_token()
    assert raw not in hash_token(raw)


def test_expiry_comparison():
    assert is_expired(datetime.now(UTC) - timedelta(seconds=1)) is True
    assert is_expired(datetime.now(UTC) + timedelta(hours=1)) is False


def test_expiry_handles_naive_datetimes_from_the_db():
    # Postgres may hand back a naive datetime depending on driver config;
    # treating it as UTC must not raise.
    assert is_expired(datetime.utcnow() - timedelta(hours=1)) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/test_token_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.token_service'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/token_service.py
import hashlib
import secrets
from datetime import UTC, datetime

_TOKEN_BYTES = 32


def generate_token() -> str:
    """Raw token for an emailed link. Never stored -- only its hash is."""
    return secrets.token_urlsafe(_TOKEN_BYTES)


def hash_token(raw: str) -> str:
    """SHA-256 hex digest. A database read cannot be turned into account
    takeover because the raw token exists only inside the emailed link."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def is_expired(expires_at: datetime) -> bool:
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at <= datetime.now(UTC)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/unit/test_token_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/token_service.py backend/tests/unit/test_token_service.py
git commit -m "feat: add hashed single-use token service"
```

---

### Task 5: Tenancy service — workspace creation and slug generation

**Files:**
- Create: `backend/app/services/tenancy_service.py`
- Test: `backend/tests/integration/test_tenancy_service.py`

**Interfaces:**
- Consumes: `Workspace`, `WorkspaceMembership`, `WorkspaceRole`, `User`
- Produces: `TenancyService(db)` with `generate_slug(name: str) -> str`, `create_workspace(name: str, owner: User) -> Workspace`, `list_memberships(user_id: UUID) -> list[WorkspaceMembership]`, `count_admins(workspace_id: UUID) -> int`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/test_tenancy_service.py
import uuid

from app.models.user import User
from app.models.workspace import WorkspaceRole
from app.services.tenancy_service import TenancyService


def _user(db) -> User:
    user = User(email=f"u-{uuid.uuid4().hex[:8]}@t.local", hashed_password="x")
    db.add(user)
    db.flush()
    return user


def test_slug_is_lowercased_and_hyphenated(db):
    assert TenancyService(db).generate_slug("Acme Corp") == "acme-corp"


def test_slug_strips_punctuation(db):
    assert TenancyService(db).generate_slug("Acme, Inc.!") == "acme-inc"


def test_slug_collision_gets_numeric_suffix(db):
    service = TenancyService(db)
    owner = _user(db)
    service.create_workspace("Dupe Test Co", owner)
    db.flush()
    assert service.generate_slug("Dupe Test Co") == "dupe-test-co-2"


def test_blank_slug_falls_back(db):
    assert TenancyService(db).generate_slug("!!!").startswith("workspace")


def test_create_workspace_makes_owner_an_admin(db):
    owner = _user(db)
    workspace = TenancyService(db).create_workspace("Acme", owner)
    db.flush()
    memberships = TenancyService(db).list_memberships(owner.id)
    assert [m.workspace_id for m in memberships] == [workspace.id]
    assert memberships[0].role == WorkspaceRole.admin


def test_count_admins(db):
    owner = _user(db)
    workspace = TenancyService(db).create_workspace("Acme", owner)
    db.flush()
    assert TenancyService(db).count_admins(workspace.id) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/integration/test_tenancy_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.tenancy_service'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/tenancy_service.py
import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
_FALLBACK_SLUG = "workspace"


class TenancyService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def generate_slug(self, name: str) -> str:
        base = _SLUG_STRIP.sub("-", name.lower()).strip("-") or _FALLBACK_SLUG
        candidate = base
        suffix = 1
        while self._slug_taken(candidate):
            suffix += 1
            candidate = f"{base}-{suffix}"
        return candidate

    def _slug_taken(self, slug: str) -> bool:
        return (
            self._db.scalars(select(Workspace).where(Workspace.slug == slug)).first() is not None
        )

    def create_workspace(self, name: str, owner: User) -> Workspace:
        workspace = Workspace(name=name, slug=self.generate_slug(name))
        self._db.add(workspace)
        self._db.flush()
        self._db.add(
            WorkspaceMembership(
                workspace_id=workspace.id, user_id=owner.id, role=WorkspaceRole.admin
            )
        )
        self._db.flush()
        return workspace

    def list_memberships(self, user_id: uuid.UUID) -> list[WorkspaceMembership]:
        return list(
            self._db.scalars(
                select(WorkspaceMembership).where(WorkspaceMembership.user_id == user_id)
            )
        )

    def count_admins(self, workspace_id: uuid.UUID) -> int:
        return self._db.scalar(
            select(func.count())
            .select_from(WorkspaceMembership)
            .where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.role == WorkspaceRole.admin,
            )
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/integration/test_tenancy_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/tenancy_service.py backend/tests/integration/test_tenancy_service.py
git commit -m "feat: add tenancy service with slug generation and workspace creation"
```

---

### Task 6: Signup and email verification endpoints

**Files:**
- Modify: `backend/app/api/v1/auth.py`
- Test: `backend/tests/integration/test_signup_flow.py`

**Interfaces:**
- Consumes: `TenancyService`, `generate_token`, `hash_token`, `is_expired`, `get_email_provider`, `verify_email_message`, `AuthToken`, `AuthTokenPurpose`
- Produces: `POST /api/v1/auth/signup` → `201 {access_token, token_type}`; `POST /api/v1/auth/verify-email` body `{token}` → `200 {"status": "verified"}`; `POST /api/v1/auth/resend-verification` body `{email}` → always `202`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/test_signup_flow.py
import re
import uuid

import pytest

from app.email.factory import get_email_provider
from app.email.provider import FakeEmailProvider
from app.main import app


@pytest.fixture
def fake_email():
    provider = FakeEmailProvider()
    app.dependency_overrides[get_email_provider] = lambda: provider
    yield provider
    app.dependency_overrides.pop(get_email_provider, None)


def _link_token(provider: FakeEmailProvider) -> str:
    match = re.search(r"token=([A-Za-z0-9_\-]+)", provider.sent[-1].text)
    assert match, f"no token in email: {provider.sent[-1].text}"
    return match.group(1)


def _signup_body(email: str) -> dict:
    return {
        "email": email,
        "password": "correct-horse-battery",
        "full_name": "Test User",
        "workspace_name": "Acme Corp",
    }


def test_signup_creates_workspace_and_sends_verification(client, fake_email):
    email = f"new-{uuid.uuid4().hex[:8]}@acme.com"
    resp = client.post("/api/v1/auth/signup", json=_signup_body(email))
    assert resp.status_code == 201
    assert resp.json()["access_token"]
    assert len(fake_email.sent) == 1
    assert fake_email.sent[0].to == email


def test_duplicate_signup_is_rejected(client, fake_email):
    email = f"dup-{uuid.uuid4().hex[:8]}@acme.com"
    client.post("/api/v1/auth/signup", json=_signup_body(email))
    resp = client.post("/api/v1/auth/signup", json=_signup_body(email))
    assert resp.status_code == 409


def test_unverified_user_is_blocked_from_documents(client, fake_email):
    email = f"unv-{uuid.uuid4().hex[:8]}@acme.com"
    token = client.post("/api/v1/auth/signup", json=_signup_body(email)).json()["access_token"]
    resp = client.get("/api/v1/documents", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403
    assert resp.json()["code"] == "email_not_verified"


def test_verification_unblocks_documents(client, fake_email):
    email = f"ver-{uuid.uuid4().hex[:8]}@acme.com"
    token = client.post("/api/v1/auth/signup", json=_signup_body(email)).json()["access_token"]
    assert client.post(
        "/api/v1/auth/verify-email", json={"token": _link_token(fake_email)}
    ).status_code == 200
    resp = client.get("/api/v1/documents", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


def test_verification_token_is_single_use(client, fake_email):
    email = f"once-{uuid.uuid4().hex[:8]}@acme.com"
    client.post("/api/v1/auth/signup", json=_signup_body(email))
    raw = _link_token(fake_email)
    client.post("/api/v1/auth/verify-email", json={"token": raw})
    resp = client.post("/api/v1/auth/verify-email", json={"token": raw})
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_token"


def test_garbage_verification_token_rejected(client, fake_email):
    resp = client.post("/api/v1/auth/verify-email", json={"token": "not-a-real-token"})
    assert resp.status_code == 400


def test_resend_verification_is_silent_for_unknown_email(client, fake_email):
    resp = client.post("/api/v1/auth/resend-verification", json={"email": "nobody@nowhere.com"})
    assert resp.status_code == 202
    assert fake_email.sent == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/integration/test_signup_flow.py -v`
Expected: FAIL — 404 on `/api/v1/auth/signup`

- [ ] **Step 3: Write minimal implementation**

In `backend/app/api/v1/auth.py`, add imports and endpoints. Note `get_email_provider` is wrapped in a FastAPI dependency so tests can override it:

```python
from datetime import UTC, datetime, timedelta

from fastapi import status
from pydantic import BaseModel, EmailStr

from app.core.errors import ConflictError, InvalidTokenError
from app.email.factory import get_email_provider
from app.email.provider import EmailProvider
from app.email.templates import verify_email_message
from app.models.auth_token import AuthToken, AuthTokenPurpose
from app.models.user import User
from app.services.tenancy_service import TenancyService
from app.services.token_service import generate_token, hash_token, is_expired
from app.core.security import hash_password

_VERIFY_TTL = timedelta(days=7)


class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str | None = None
    workspace_name: str


class SimpleStatusResponse(BaseModel):
    status: str


class TokenOnlyRequest(BaseModel):
    token: str


class EmailOnlyRequest(BaseModel):
    email: EmailStr


def _issue_verification_email(
    db: Session, user: User, email_provider: EmailProvider
) -> None:
    raw = generate_token()
    db.add(
        AuthToken(
            user_id=user.id,
            purpose=AuthTokenPurpose.verify_email,
            token_hash=hash_token(raw),
            expires_at=datetime.now(UTC) + _VERIFY_TTL,
        )
    )
    db.flush()
    link = f"{get_settings().FRONTEND_BASE_URL}/verify-email?token={raw}"
    email_provider.send(verify_email_message(user.email, link))


@router.post("/signup", response_model=LoginResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(get_settings().RATE_LIMIT_SIGNUP)
def signup(
    request: Request,
    payload: SignupRequest,
    db: Session = Depends(get_db),
    email_provider: EmailProvider = Depends(get_email_provider),
) -> LoginResponse:
    repo = WorkspaceRepository(db)
    if repo.get_user_by_email(payload.email) is not None:
        log_audit_event("auth.signup.failure", email=payload.email, reason="email_taken")
        raise ConflictError("An account with that email already exists", code="email_taken")

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
    )
    db.add(user)
    db.flush()

    workspace = TenancyService(db).create_workspace(payload.workspace_name, user)
    _issue_verification_email(db, user, email_provider)
    db.commit()

    log_audit_event(
        "auth.signup.success", user_id=str(user.id), workspace_id=str(workspace.id)
    )
    return LoginResponse(access_token=create_access_token(user.id, workspace.id))


@router.post("/verify-email", response_model=SimpleStatusResponse)
def verify_email(payload: TokenOnlyRequest, db: Session = Depends(get_db)) -> SimpleStatusResponse:
    token = db.scalars(
        select(AuthToken).where(
            AuthToken.token_hash == hash_token(payload.token),
            AuthToken.purpose == AuthTokenPurpose.verify_email,
        )
    ).first()
    if token is None or token.used_at is not None:
        raise InvalidTokenError()
    if is_expired(token.expires_at):
        raise TokenExpiredError()

    user = db.get(User, token.user_id)
    now = datetime.now(UTC)
    user.email_verified_at = now
    token.used_at = now
    db.commit()

    log_audit_event("auth.email_verified", user_id=str(user.id))
    return SimpleStatusResponse(status="verified")


@router.post(
    "/resend-verification",
    response_model=SimpleStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
@limiter.limit(get_settings().RATE_LIMIT_SIGNUP)
def resend_verification(
    request: Request,
    payload: EmailOnlyRequest,
    db: Session = Depends(get_db),
    email_provider: EmailProvider = Depends(get_email_provider),
) -> SimpleStatusResponse:
    """Always 202 regardless of whether the address exists -- this endpoint
    must not reveal who has an account."""
    user = WorkspaceRepository(db).get_user_by_email(payload.email)
    if user is not None and user.email_verified_at is None:
        _issue_verification_email(db, user, email_provider)
        db.commit()
    return SimpleStatusResponse(status="accepted")
```

Also import `TokenExpiredError` at the top.

The unverified-user gate lives in `deps.py` and is built in Task 7 — until that task lands, `test_unverified_user_is_blocked_from_documents` will fail. Implement Task 7 before re-running the full file, or mark that one test `xfail` and remove the marker in Task 7.

- [ ] **Step 4: Run the tests that do not depend on Task 7**

Run: `cd backend && pytest tests/integration/test_signup_flow.py -v -k "not blocked and not unblocks"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/auth.py backend/tests/integration/test_signup_flow.py
git commit -m "feat: add signup and email verification endpoints"
```

---

### Task 7: Membership re-check, verified gate, and require_admin

Closes the live isolation gap: `get_current_user` currently trusts a 24-hour-old `workspace_id` claim and never re-checks membership.

**Files:**
- Modify: `backend/app/api/deps.py`
- Test: `backend/tests/integration/test_membership_enforcement.py`

**Interfaces:**
- Consumes: `WorkspaceRepository.get_membership`, `EmailNotVerifiedError`
- Produces: `get_current_user(...)` now DB-backed and returning `CurrentUser(user_id, workspace_id, role, email_verified)`; `require_admin(current_user) -> CurrentUser`; `invalidate_membership_cache(user_id, workspace_id) -> None`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/test_membership_enforcement.py
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.api.deps import invalidate_membership_cache
from app.core.security import create_access_token
from app.models.user import User
from app.models.workspace import WorkspaceMembership, WorkspaceRole
from app.services.tenancy_service import TenancyService


def _membership(db, user_id, workspace_id) -> WorkspaceMembership:
    return db.scalars(
        select(WorkspaceMembership).where(
            WorkspaceMembership.user_id == user_id,
            WorkspaceMembership.workspace_id == workspace_id,
        )
    ).first()


def _verified_user(db, role=WorkspaceRole.admin):
    user = User(
        email=f"u-{uuid.uuid4().hex[:8]}@t.local",
        hashed_password="x",
        email_verified_at=datetime.now(UTC),
    )
    db.add(user)
    db.flush()
    workspace = TenancyService(db).create_workspace("Acme", user)
    if role is WorkspaceRole.member:
        _membership(db, user.id, workspace.id).role = WorkspaceRole.member
    db.commit()
    return user, workspace


def test_valid_member_is_accepted(client, db):
    user, workspace = _verified_user(db)
    token = create_access_token(user.id, workspace.id)
    resp = client.get("/api/v1/documents", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


def test_removed_member_loses_access(client, db):
    user, workspace = _verified_user(db)
    token = create_access_token(user.id, workspace.id)
    assert client.get(
        "/api/v1/documents", headers={"Authorization": f"Bearer {token}"}
    ).status_code == 200

    db.delete(_membership(db, user.id, workspace.id))
    db.commit()
    invalidate_membership_cache(user.id, workspace.id)

    resp = client.get("/api/v1/documents", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_token_for_a_workspace_you_never_joined_is_rejected(client, db):
    user, _ = _verified_user(db)
    other_workspace_id = uuid.uuid4()
    token = create_access_token(user.id, other_workspace_id)
    resp = client.get("/api/v1/documents", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_inactive_user_is_rejected(client, db):
    user, workspace = _verified_user(db)
    token = create_access_token(user.id, workspace.id)
    user.is_active = False
    db.commit()
    invalidate_membership_cache(user.id, workspace.id)
    resp = client.get("/api/v1/documents", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/integration/test_membership_enforcement.py -v`
Expected: FAIL — `ImportError: cannot import name 'invalidate_membership_cache'`; `test_removed_member_loses_access` returns 200 because nothing re-checks membership.

- [ ] **Step 3: Write minimal implementation**

Replace the body of `backend/app/api/deps.py`:

```python
import uuid
from dataclasses import dataclass

import redis
from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import EmailNotVerifiedError, PermissionDeniedError
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.user import User
from app.models.workspace import WorkspaceRole
from app.repositories.workspace_repository import WorkspaceRepository

_MEMBERSHIP_TTL_SECONDS = 60


@dataclass(frozen=True)
class CurrentUser:
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    role: WorkspaceRole
    email_verified: bool


def _cache() -> redis.Redis:
    return redis.Redis.from_url(get_settings().REDIS_URL, decode_responses=True)


def _cache_key(user_id: uuid.UUID, workspace_id: uuid.UUID) -> str:
    return f"membership:{user_id}:{workspace_id}"


def invalidate_membership_cache(user_id: uuid.UUID, workspace_id: uuid.UUID) -> None:
    """Call after any membership or role change so revocation takes effect
    immediately rather than after the TTL."""
    try:
        _cache().delete(_cache_key(user_id, workspace_id))
    except redis.RedisError:
        pass  # cache is an optimisation; the DB remains authoritative


def _resolve_membership(
    db: Session, user_id: uuid.UUID, workspace_id: uuid.UUID
) -> tuple[WorkspaceRole, bool]:
    """Returns (role, email_verified). Raises if the membership is gone."""
    key = _cache_key(user_id, workspace_id)
    try:
        cached = _cache().get(key)
    except redis.RedisError:
        cached = None
    if cached:
        role_value, verified_flag = cached.split("|", 1)
        return WorkspaceRole(role_value), verified_flag == "1"

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise PermissionDeniedError("User is not active")
    membership = WorkspaceRepository(db).get_membership(user_id, workspace_id)
    if membership is None:
        raise PermissionDeniedError("You are not a member of this workspace")

    verified = user.email_verified_at is not None
    try:
        _cache().setex(
            key, _MEMBERSHIP_TTL_SECONDS, f"{membership.role.value}|{'1' if verified else '0'}"
        )
    except redis.RedisError:
        pass
    return membership.role, verified


def get_current_user(
    authorization: str = Header(...), db: Session = Depends(get_db)
) -> CurrentUser:
    if not authorization.startswith("Bearer "):
        raise PermissionDeniedError("Missing bearer token")
    token = authorization.removeprefix("Bearer ")
    try:
        payload = decode_access_token(token)
    except Exception as exc:
        raise PermissionDeniedError("Invalid or expired token") from exc

    user_id = uuid.UUID(payload["sub"])
    workspace_id = uuid.UUID(payload["workspace_id"])
    role, email_verified = _resolve_membership(db, user_id, workspace_id)
    if not email_verified:
        raise EmailNotVerifiedError()
    return CurrentUser(
        user_id=user_id, workspace_id=workspace_id, role=role, email_verified=email_verified
    )


def get_current_user_allow_unverified(
    authorization: str = Header(...), db: Session = Depends(get_db)
) -> CurrentUser:
    """For the handful of endpoints an unverified user must still reach:
    /auth/me, /auth/switch-workspace, GET /workspaces, /invitations/accept."""
    if not authorization.startswith("Bearer "):
        raise PermissionDeniedError("Missing bearer token")
    token = authorization.removeprefix("Bearer ")
    try:
        payload = decode_access_token(token)
    except Exception as exc:
        raise PermissionDeniedError("Invalid or expired token") from exc
    user_id = uuid.UUID(payload["sub"])
    workspace_id = uuid.UUID(payload["workspace_id"])
    role, email_verified = _resolve_membership(db, user_id, workspace_id)
    return CurrentUser(
        user_id=user_id, workspace_id=workspace_id, role=role, email_verified=email_verified
    )


def require_admin(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if current_user.role is not WorkspaceRole.admin:
        raise PermissionDeniedError(
            "This action requires workspace admin", code="admin_required"
        )
    return current_user
```

Confirm `WorkspaceRepository.get_membership` accepts `(user_id, workspace_id)` in that order — check `app/repositories/workspace_repository.py:17` and match it.

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd backend && pytest tests/integration/test_membership_enforcement.py tests/integration/test_signup_flow.py tests/integration/test_permission_isolation.py -v
```
Expected: PASS, including the two Task 6 tests that were skipped and the pre-existing isolation suite.

- [ ] **Step 5: Apply require_admin to connector management**

The spec gates connector connect/disconnect on admin. Add this test:

```python
# append to backend/tests/integration/test_membership_enforcement.py
def test_member_cannot_start_connector_oauth(client, db):
    from app.api.deps import invalidate_membership_cache

    user, workspace = _verified_user(db, role=WorkspaceRole.member)
    invalidate_membership_cache(user.id, workspace.id)
    token = create_access_token(user.id, workspace.id)
    resp = client.get(
        "/api/v1/connectors/google/oauth/start?connector_type=google_drive",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "admin_required"


def test_member_can_still_sync_their_own_connector(client, db):
    """Syncing your own connection is a member action -- only connecting and
    disconnecting are admin-gated."""
    user, workspace = _verified_user(db, role=WorkspaceRole.member)
    invalidate_membership_cache(user.id, workspace.id)
    token = create_access_token(user.id, workspace.id)
    resp = client.post(
        "/api/v1/connectors/google-drive/sync",
        headers={"Authorization": f"Bearer {token}"},
    )
    # 404 (no connection of their own yet), never 403.
    assert resp.status_code != 403
```

In `backend/app/api/v1/connectors.py`, change the OAuth start endpoint's dependency from `Depends(get_current_user)` to `Depends(require_admin)`, importing `require_admin` from `app.api.deps`. Leave the two `/sync` endpoints on `get_current_user` — syncing your own connection is a member action.

The OAuth **callback** stays unauthenticated: it is hit by the browser redirecting from Google and is authorised by the signed `state` token, per the docstring at `app/core/security.py`.

- [ ] **Step 6: Run the whole suite — this task changes a dependency every endpoint uses**

Run: `cd backend && pytest -v`
Expected: PASS. Any existing test constructing `CurrentUser(user_id=..., workspace_id=...)` positionally must be updated for the two new fields.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/deps.py backend/app/api/v1/connectors.py backend/tests/integration/test_membership_enforcement.py
git commit -m "feat: re-check membership per request and add require_admin"
```

---

### Task 8: Password reset

**Files:**
- Modify: `backend/app/api/v1/auth.py`
- Test: `backend/tests/integration/test_password_reset.py`

**Interfaces:**
- Consumes: `AuthToken`, `AuthTokenPurpose.password_reset`, `password_reset_message`, `hash_password`
- Produces: `POST /api/v1/auth/forgot-password` body `{email}` → always `202`; `POST /api/v1/auth/reset-password` body `{token, new_password}` → `200 {"status": "reset"}`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/test_password_reset.py
import re
import uuid

import pytest

from app.email.factory import get_email_provider
from app.email.provider import FakeEmailProvider
from app.main import app


@pytest.fixture
def fake_email():
    provider = FakeEmailProvider()
    app.dependency_overrides[get_email_provider] = lambda: provider
    yield provider
    app.dependency_overrides.pop(get_email_provider, None)


def _signup(client, email: str) -> None:
    client.post(
        "/api/v1/auth/signup",
        json={
            "email": email,
            "password": "original-password",
            "full_name": "T",
            "workspace_name": "Acme",
        },
    )


def _link_token(provider: FakeEmailProvider) -> str:
    return re.search(r"token=([A-Za-z0-9_\-]+)", provider.sent[-1].text).group(1)


def test_forgot_password_returns_202_for_unknown_email(client, fake_email):
    resp = client.post("/api/v1/auth/forgot-password", json={"email": "ghost@nowhere.com"})
    assert resp.status_code == 202
    assert fake_email.sent == []


def test_forgot_password_response_is_identical_for_known_and_unknown(client, fake_email):
    email = f"known-{uuid.uuid4().hex[:8]}@acme.com"
    _signup(client, email)
    known = client.post("/api/v1/auth/forgot-password", json={"email": email})
    unknown = client.post("/api/v1/auth/forgot-password", json={"email": "ghost@nowhere.com"})
    assert known.status_code == unknown.status_code
    assert known.json() == unknown.json()


def test_reset_changes_the_password(client, fake_email):
    email = f"reset-{uuid.uuid4().hex[:8]}@acme.com"
    _signup(client, email)
    client.post("/api/v1/auth/forgot-password", json={"email": email})
    raw = _link_token(fake_email)

    assert client.post(
        "/api/v1/auth/reset-password", json={"token": raw, "new_password": "brand-new-password"}
    ).status_code == 200
    assert client.post(
        "/api/v1/auth/login", json={"email": email, "password": "brand-new-password"}
    ).status_code == 200
    assert client.post(
        "/api/v1/auth/login", json={"email": email, "password": "original-password"}
    ).status_code == 401


def test_reset_token_is_single_use(client, fake_email):
    email = f"once-{uuid.uuid4().hex[:8]}@acme.com"
    _signup(client, email)
    client.post("/api/v1/auth/forgot-password", json={"email": email})
    raw = _link_token(fake_email)
    client.post("/api/v1/auth/reset-password", json={"token": raw, "new_password": "first-change"})
    resp = client.post(
        "/api/v1/auth/reset-password", json={"token": raw, "new_password": "second-change"}
    )
    assert resp.status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/integration/test_password_reset.py -v`
Expected: FAIL — 404 on `/api/v1/auth/forgot-password`

- [ ] **Step 3: Write minimal implementation**

Append to `backend/app/api/v1/auth.py`:

```python
_RESET_TTL = timedelta(hours=1)


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


@router.post(
    "/forgot-password",
    response_model=SimpleStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
@limiter.limit(get_settings().RATE_LIMIT_PASSWORD_RESET)
def forgot_password(
    request: Request,
    payload: EmailOnlyRequest,
    db: Session = Depends(get_db),
    email_provider: EmailProvider = Depends(get_email_provider),
) -> SimpleStatusResponse:
    """Always 202 with an identical body, whether or not the address exists --
    otherwise this endpoint becomes a customer-enumeration oracle."""
    user = WorkspaceRepository(db).get_user_by_email(payload.email)
    if user is not None:
        raw = generate_token()
        db.add(
            AuthToken(
                user_id=user.id,
                purpose=AuthTokenPurpose.password_reset,
                token_hash=hash_token(raw),
                expires_at=datetime.now(UTC) + _RESET_TTL,
            )
        )
        db.flush()
        link = f"{get_settings().FRONTEND_BASE_URL}/reset-password?token={raw}"
        email_provider.send(password_reset_message(user.email, link))
        db.commit()
        log_audit_event("auth.password_reset.requested", user_id=str(user.id))
    return SimpleStatusResponse(status="accepted")


@router.post("/reset-password", response_model=SimpleStatusResponse)
def reset_password(
    payload: ResetPasswordRequest, db: Session = Depends(get_db)
) -> SimpleStatusResponse:
    token = db.scalars(
        select(AuthToken).where(
            AuthToken.token_hash == hash_token(payload.token),
            AuthToken.purpose == AuthTokenPurpose.password_reset,
        )
    ).first()
    if token is None or token.used_at is not None:
        raise InvalidTokenError()
    if is_expired(token.expires_at):
        raise TokenExpiredError()

    user = db.get(User, token.user_id)
    user.hashed_password = hash_password(payload.new_password)
    token.used_at = datetime.now(UTC)
    db.commit()

    log_audit_event("auth.password_reset.completed", user_id=str(user.id))
    return SimpleStatusResponse(status="reset")
```

Add `password_reset_message` to the imports from `app.email.templates`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/integration/test_password_reset.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/auth.py backend/tests/integration/test_password_reset.py
git commit -m "feat: add enumeration-resistant password reset"
```

---

### Task 9: Multi-workspace — /auth/me, workspace list, switching

**Files:**
- Modify: `backend/app/api/v1/auth.py`
- Create: `backend/app/api/v1/workspaces.py`
- Modify: `backend/app/api/v1/router.py`
- Test: `backend/tests/integration/test_multi_workspace.py`

**Interfaces:**
- Consumes: `TenancyService.list_memberships`, `create_workspace`, `get_current_user_allow_unverified`
- Produces: `GET /api/v1/auth/me` → `{user_id, email, full_name, email_verified, active_workspace_id, role, workspaces: [{id, name, slug, role}]}`; `POST /api/v1/auth/switch-workspace` body `{workspace_id}` → `{access_token, token_type}`; `GET /api/v1/workspaces`; `POST /api/v1/workspaces` body `{name}` → `201`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/test_multi_workspace.py
import re
import uuid

import pytest

from app.email.factory import get_email_provider
from app.email.provider import FakeEmailProvider
from app.main import app


@pytest.fixture
def fake_email():
    provider = FakeEmailProvider()
    app.dependency_overrides[get_email_provider] = lambda: provider
    yield provider
    app.dependency_overrides.pop(get_email_provider, None)


def _verified_signup(client, fake_email, workspace_name="Acme") -> tuple[str, str]:
    email = f"u-{uuid.uuid4().hex[:8]}@acme.com"
    token = client.post(
        "/api/v1/auth/signup",
        json={
            "email": email,
            "password": "pw-pw-pw-pw",
            "full_name": "T",
            "workspace_name": workspace_name,
        },
    ).json()["access_token"]
    raw = re.search(r"token=([A-Za-z0-9_\-]+)", fake_email.sent[-1].text).group(1)
    client.post("/api/v1/auth/verify-email", json={"token": raw})
    return token, email


def test_me_reports_identity_and_workspaces(client, fake_email):
    token, email = _verified_signup(client, fake_email)
    body = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert body["email"] == email
    assert body["email_verified"] is True
    assert body["role"] == "admin"
    assert len(body["workspaces"]) == 1


def test_creating_a_second_workspace_shows_in_me(client, fake_email):
    token, _ = _verified_signup(client, fake_email)
    headers = {"Authorization": f"Bearer {token}"}
    assert client.post("/api/v1/workspaces", json={"name": "Second Co"}, headers=headers).status_code == 201
    body = client.get("/api/v1/auth/me", headers=headers).json()
    assert {w["name"] for w in body["workspaces"]} == {"Acme", "Second Co"}


def test_switching_returns_a_token_scoped_to_the_new_workspace(client, fake_email):
    token, _ = _verified_signup(client, fake_email)
    headers = {"Authorization": f"Bearer {token}"}
    second = client.post("/api/v1/workspaces", json={"name": "Second Co"}, headers=headers).json()

    switched = client.post(
        "/api/v1/auth/switch-workspace", json={"workspace_id": second["id"]}, headers=headers
    ).json()["access_token"]
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {switched}"}).json()
    assert me["active_workspace_id"] == second["id"]


def test_cannot_switch_into_a_workspace_you_do_not_belong_to(client, fake_email):
    token, _ = _verified_signup(client, fake_email)
    resp = client.post(
        "/api/v1/auth/switch-workspace",
        json={"workspace_id": str(uuid.uuid4())},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_switched_token_cannot_read_the_other_workspaces_documents(client, fake_email):
    """The load-bearing isolation test: switching must not leak across tenants."""
    token, _ = _verified_signup(client, fake_email)
    headers = {"Authorization": f"Bearer {token}"}
    second = client.post("/api/v1/workspaces", json={"name": "Second Co"}, headers=headers).json()
    switched = client.post(
        "/api/v1/auth/switch-workspace", json={"workspace_id": second["id"]}, headers=headers
    ).json()["access_token"]

    docs = client.get(
        "/api/v1/documents", headers={"Authorization": f"Bearer {switched}"}
    ).json()
    assert docs == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/integration/test_multi_workspace.py -v`
Expected: FAIL — 404 on `/api/v1/auth/me`

- [ ] **Step 3: Write minimal implementation**

Append to `backend/app/api/v1/auth.py`:

```python
from app.api.deps import CurrentUser, get_current_user_allow_unverified
from app.models.workspace import Workspace


class WorkspaceSummary(BaseModel):
    id: str
    name: str
    slug: str
    role: str


class MeResponse(BaseModel):
    user_id: str
    email: str
    full_name: str | None
    email_verified: bool
    active_workspace_id: str
    role: str
    workspaces: list[WorkspaceSummary]


class SwitchWorkspaceRequest(BaseModel):
    workspace_id: uuid.UUID


@router.get("/me", response_model=MeResponse)
def me(
    current_user: CurrentUser = Depends(get_current_user_allow_unverified),
    db: Session = Depends(get_db),
) -> MeResponse:
    user = db.get(User, current_user.user_id)
    memberships = TenancyService(db).list_memberships(user.id)
    summaries = []
    for membership in memberships:
        workspace = db.get(Workspace, membership.workspace_id)
        summaries.append(
            WorkspaceSummary(
                id=str(workspace.id),
                name=workspace.name,
                slug=workspace.slug,
                role=membership.role.value,
            )
        )
    return MeResponse(
        user_id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        email_verified=user.email_verified_at is not None,
        active_workspace_id=str(current_user.workspace_id),
        role=current_user.role.value,
        workspaces=summaries,
    )


@router.post("/switch-workspace", response_model=LoginResponse)
def switch_workspace(
    payload: SwitchWorkspaceRequest,
    current_user: CurrentUser = Depends(get_current_user_allow_unverified),
    db: Session = Depends(get_db),
) -> LoginResponse:
    membership = WorkspaceRepository(db).get_membership(
        current_user.user_id, payload.workspace_id
    )
    if membership is None:
        raise PermissionDeniedError("You are not a member of that workspace")
    log_audit_event(
        "auth.workspace_switched",
        user_id=str(current_user.user_id),
        workspace_id=str(payload.workspace_id),
    )
    return LoginResponse(
        access_token=create_access_token(current_user.user_id, payload.workspace_id)
    )
```

Add `import uuid` and `from app.core.errors import PermissionDeniedError` at the top.

Create `backend/app/api/v1/workspaces.py`:

```python
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_current_user, get_current_user_allow_unverified
from app.core.audit import log_audit_event
from app.db.session import get_db
from app.models.user import User
from app.models.workspace import Workspace
from app.services.tenancy_service import TenancyService

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


class WorkspaceResponse(BaseModel):
    id: str
    name: str
    slug: str
    role: str


class CreateWorkspaceRequest(BaseModel):
    name: str


@router.get("", response_model=list[WorkspaceResponse])
def list_workspaces(
    current_user: CurrentUser = Depends(get_current_user_allow_unverified),
    db: Session = Depends(get_db),
) -> list[WorkspaceResponse]:
    out = []
    for membership in TenancyService(db).list_memberships(current_user.user_id):
        workspace = db.get(Workspace, membership.workspace_id)
        out.append(
            WorkspaceResponse(
                id=str(workspace.id),
                name=workspace.name,
                slug=workspace.slug,
                role=membership.role.value,
            )
        )
    return out


@router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
def create_workspace(
    payload: CreateWorkspaceRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkspaceResponse:
    user = db.get(User, current_user.user_id)
    workspace = TenancyService(db).create_workspace(payload.name, user)
    db.commit()
    log_audit_event(
        "workspace.created", user_id=str(user.id), workspace_id=str(workspace.id)
    )
    return WorkspaceResponse(
        id=str(workspace.id), name=workspace.name, slug=workspace.slug, role="admin"
    )
```

Register it in `backend/app/api/v1/router.py` following the existing `include_router` pattern.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/integration/test_multi_workspace.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/auth.py backend/app/api/v1/workspaces.py backend/app/api/v1/router.py backend/tests/integration/test_multi_workspace.py
git commit -m "feat: add /auth/me, workspace list/create, and workspace switching"
```

---

### Task 10: Member management with last-admin protection

**Files:**
- Modify: `backend/app/api/v1/workspaces.py`, `backend/app/services/tenancy_service.py`
- Test: `backend/tests/integration/test_member_management.py`

**Interfaces:**
- Consumes: `require_admin`, `TenancyService.count_admins`, `invalidate_membership_cache`
- Produces: `GET /api/v1/workspaces/current/members` → `[{user_id, email, full_name, role}]`; `PATCH .../members/{user_id}` body `{role}`; `DELETE .../members/{user_id}`; `TenancyService.change_role(workspace_id, user_id, role)`, `.remove_member(workspace_id, user_id)`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/test_member_management.py
import re
import uuid

import pytest

from app.email.factory import get_email_provider
from app.email.provider import FakeEmailProvider
from app.main import app


@pytest.fixture
def fake_email():
    provider = FakeEmailProvider()
    app.dependency_overrides[get_email_provider] = lambda: provider
    yield provider
    app.dependency_overrides.pop(get_email_provider, None)


def _verified_admin(client, fake_email) -> tuple[str, str]:
    email = f"admin-{uuid.uuid4().hex[:8]}@acme.com"
    token = client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "pw-pw-pw-pw", "full_name": "A", "workspace_name": "Acme"},
    ).json()["access_token"]
    raw = re.search(r"token=([A-Za-z0-9_\-]+)", fake_email.sent[-1].text).group(1)
    client.post("/api/v1/auth/verify-email", json={"token": raw})
    return token, email


def test_admin_sees_the_member_list(client, fake_email):
    token, email = _verified_admin(client, fake_email)
    body = client.get(
        "/api/v1/workspaces/current/members", headers={"Authorization": f"Bearer {token}"}
    ).json()
    assert [m["email"] for m in body] == [email]
    assert body[0]["role"] == "admin"


def test_cannot_demote_the_last_admin(client, fake_email):
    token, _ = _verified_admin(client, fake_email)
    headers = {"Authorization": f"Bearer {token}"}
    me = client.get("/api/v1/auth/me", headers=headers).json()
    resp = client.patch(
        f"/api/v1/workspaces/current/members/{me['user_id']}",
        json={"role": "member"},
        headers=headers,
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "last_admin"


def test_cannot_remove_the_last_admin(client, fake_email):
    token, _ = _verified_admin(client, fake_email)
    headers = {"Authorization": f"Bearer {token}"}
    me = client.get("/api/v1/auth/me", headers=headers).json()
    resp = client.delete(
        f"/api/v1/workspaces/current/members/{me['user_id']}", headers=headers
    )
    assert resp.status_code == 409


def test_member_cannot_reach_admin_endpoints(client, fake_email, db):
    from sqlalchemy import select

    from app.api.deps import invalidate_membership_cache
    from app.models.workspace import WorkspaceMembership, WorkspaceRole

    token, _ = _verified_admin(client, fake_email)
    headers = {"Authorization": f"Bearer {token}"}
    me = client.get("/api/v1/auth/me", headers=headers).json()

    membership = db.scalars(
        select(WorkspaceMembership).where(
            WorkspaceMembership.user_id == uuid.UUID(me["user_id"])
        )
    ).first()
    membership.role = WorkspaceRole.member
    db.commit()
    invalidate_membership_cache(
        uuid.UUID(me["user_id"]), uuid.UUID(me["active_workspace_id"])
    )

    resp = client.get("/api/v1/workspaces/current/members", headers=headers)
    assert resp.status_code == 403
    assert resp.json()["code"] == "admin_required"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/integration/test_member_management.py -v`
Expected: FAIL — 404 on `/api/v1/workspaces/current/members`

- [ ] **Step 3: Write minimal implementation**

Add to `TenancyService`:

```python
    def change_role(
        self, workspace_id: uuid.UUID, user_id: uuid.UUID, role: WorkspaceRole
    ) -> WorkspaceMembership:
        membership = self._get_membership_or_raise(workspace_id, user_id)
        if (
            membership.role is WorkspaceRole.admin
            and role is WorkspaceRole.member
            and self.count_admins(workspace_id) <= 1
        ):
            raise ConflictError(
                "A workspace must keep at least one admin", code="last_admin"
            )
        membership.role = role
        self._db.flush()
        return membership

    def remove_member(self, workspace_id: uuid.UUID, user_id: uuid.UUID) -> None:
        membership = self._get_membership_or_raise(workspace_id, user_id)
        if membership.role is WorkspaceRole.admin and self.count_admins(workspace_id) <= 1:
            raise ConflictError(
                "A workspace must keep at least one admin", code="last_admin"
            )
        self._db.delete(membership)
        self._db.flush()

    def _get_membership_or_raise(
        self, workspace_id: uuid.UUID, user_id: uuid.UUID
    ) -> WorkspaceMembership:
        membership = self._db.scalars(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.user_id == user_id,
            )
        ).first()
        if membership is None:
            raise NotFoundError("That person is not a member of this workspace")
        return membership
```

Import `ConflictError` and `NotFoundError` from `app.core.errors`.

Add to `backend/app/api/v1/workspaces.py`:

```python
from app.api.deps import invalidate_membership_cache, require_admin
from app.models.workspace import WorkspaceMembership, WorkspaceRole


class MemberResponse(BaseModel):
    user_id: str
    email: str
    full_name: str | None
    role: str


class ChangeRoleRequest(BaseModel):
    role: WorkspaceRole


@router.get("/current/members", response_model=list[MemberResponse])
def list_members(
    current_user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)
) -> list[MemberResponse]:
    memberships = db.scalars(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == current_user.workspace_id
        )
    ).all()
    out = []
    for membership in memberships:
        user = db.get(User, membership.user_id)
        out.append(
            MemberResponse(
                user_id=str(user.id),
                email=user.email,
                full_name=user.full_name,
                role=membership.role.value,
            )
        )
    return out


@router.patch("/current/members/{user_id}", response_model=MemberResponse)
def change_member_role(
    user_id: uuid.UUID,
    payload: ChangeRoleRequest,
    current_user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> MemberResponse:
    membership = TenancyService(db).change_role(
        current_user.workspace_id, user_id, payload.role
    )
    db.commit()
    invalidate_membership_cache(user_id, current_user.workspace_id)
    log_audit_event(
        "workspace.member_role_changed",
        actor_user_id=str(current_user.user_id),
        user_id=str(user_id),
        workspace_id=str(current_user.workspace_id),
        role=payload.role.value,
    )
    user = db.get(User, user_id)
    return MemberResponse(
        user_id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        role=membership.role.value,
    )


@router.delete("/current/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    user_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> None:
    TenancyService(db).remove_member(current_user.workspace_id, user_id)
    db.commit()
    invalidate_membership_cache(user_id, current_user.workspace_id)
    log_audit_event(
        "workspace.member_removed",
        actor_user_id=str(current_user.user_id),
        user_id=str(user_id),
        workspace_id=str(current_user.workspace_id),
    )
```

Add `import uuid`, `from sqlalchemy import select`, and the `PATCH /current` rename endpoint:

```python
class RenameWorkspaceRequest(BaseModel):
    name: str


@router.patch("/current", response_model=WorkspaceResponse)
def rename_workspace(
    payload: RenameWorkspaceRequest,
    current_user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> WorkspaceResponse:
    workspace = db.get(Workspace, current_user.workspace_id)
    workspace.name = payload.name
    db.commit()
    log_audit_event(
        "workspace.renamed",
        user_id=str(current_user.user_id),
        workspace_id=str(workspace.id),
    )
    return WorkspaceResponse(
        id=str(workspace.id),
        name=workspace.name,
        slug=workspace.slug,
        role=current_user.role.value,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/integration/test_member_management.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/workspaces.py backend/app/services/tenancy_service.py backend/tests/integration/test_member_management.py
git commit -m "feat: add member management with last-admin protection"
```

---

### Task 11: Invitations

**Files:**
- Create: `backend/app/services/invitation_service.py`, `backend/app/api/v1/invitations.py`
- Modify: `backend/app/api/v1/router.py`
- Test: `backend/tests/integration/test_invitations.py`

**Interfaces:**
- Consumes: `require_admin`, `get_current_user_allow_unverified`, `TenancyService`, token service, `invite_message`
- Produces: `POST /api/v1/invitations` body `{email, role}` → `201 {id, email, role, expires_at}`; `GET /api/v1/invitations`; `DELETE /api/v1/invitations/{id}` → `204`; `GET /api/v1/invitations/preview?token=` → `{workspace_name, email}` (unauthenticated); `POST /api/v1/invitations/accept` body `{token}` → `{access_token, token_type}`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/test_invitations.py
import re
import uuid

import pytest

from app.email.factory import get_email_provider
from app.email.provider import FakeEmailProvider
from app.main import app


@pytest.fixture
def fake_email():
    provider = FakeEmailProvider()
    app.dependency_overrides[get_email_provider] = lambda: provider
    yield provider
    app.dependency_overrides.pop(get_email_provider, None)


def _verified_admin(client, fake_email) -> tuple[str, str]:
    email = f"admin-{uuid.uuid4().hex[:8]}@acme.com"
    token = client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "pw-pw-pw-pw", "full_name": "A", "workspace_name": "Acme"},
    ).json()["access_token"]
    raw = re.search(r"token=([A-Za-z0-9_\-]+)", fake_email.sent[-1].text).group(1)
    client.post("/api/v1/auth/verify-email", json={"token": raw})
    return token, email


def _invite_token(provider: FakeEmailProvider) -> str:
    return re.search(r"token=([A-Za-z0-9_\-]+)", provider.sent[-1].text).group(1)


def test_admin_can_invite_and_email_is_sent(client, fake_email):
    token, _ = _verified_admin(client, fake_email)
    invitee = f"new-{uuid.uuid4().hex[:8]}@acme.com"
    resp = client.post(
        "/api/v1/invitations",
        json={"email": invitee, "role": "member"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    assert fake_email.sent[-1].to == invitee
    assert "Acme" in fake_email.sent[-1].text


def test_preview_reveals_workspace_without_auth(client, fake_email):
    token, _ = _verified_admin(client, fake_email)
    invitee = f"prev-{uuid.uuid4().hex[:8]}@acme.com"
    client.post(
        "/api/v1/invitations",
        json={"email": invitee, "role": "member"},
        headers={"Authorization": f"Bearer {token}"},
    )
    body = client.get(
        f"/api/v1/invitations/preview?token={_invite_token(fake_email)}"
    ).json()
    assert body["workspace_name"] == "Acme"
    assert body["email"] == invitee


def test_new_user_accepting_an_invite_is_auto_verified(client, fake_email):
    token, _ = _verified_admin(client, fake_email)
    invitee = f"join-{uuid.uuid4().hex[:8]}@acme.com"
    client.post(
        "/api/v1/invitations",
        json={"email": invitee, "role": "member"},
        headers={"Authorization": f"Bearer {token}"},
    )
    accepted = client.post(
        "/api/v1/invitations/accept",
        json={"token": _invite_token(fake_email), "password": "new-user-pw", "full_name": "N"},
    )
    assert accepted.status_code == 200
    new_token = accepted.json()["access_token"]
    # Auto-verified: receiving the invite proved they own the address.
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {new_token}"}).json()
    assert me["email_verified"] is True
    assert me["role"] == "member"


def test_logged_in_user_with_a_different_email_cannot_accept(client, fake_email):
    """Otherwise the membership would silently attach to the invited
    address's account rather than the person clicking the link."""
    admin_token, _ = _verified_admin(client, fake_email)
    other_token, _ = _verified_admin(client, fake_email)  # a different account
    invitee = f"someone-else-{uuid.uuid4().hex[:8]}@acme.com"
    client.post(
        "/api/v1/invitations",
        json={"email": invitee, "role": "member"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    resp = client.post(
        "/api/v1/invitations/accept",
        json={"token": _invite_token(fake_email)},
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "invite_email_mismatch"


def test_inviting_an_existing_member_conflicts(client, fake_email):
    token, admin_email = _verified_admin(client, fake_email)
    resp = client.post(
        "/api/v1/invitations",
        json={"email": admin_email, "role": "member"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "already_member"


def test_duplicate_pending_invite_conflicts(client, fake_email):
    token, _ = _verified_admin(client, fake_email)
    invitee = f"dup-{uuid.uuid4().hex[:8]}@acme.com"
    headers = {"Authorization": f"Bearer {token}"}
    client.post("/api/v1/invitations", json={"email": invitee, "role": "member"}, headers=headers)
    resp = client.post(
        "/api/v1/invitations", json={"email": invitee, "role": "member"}, headers=headers
    )
    assert resp.status_code == 409


def test_revoked_invite_cannot_be_accepted(client, fake_email):
    token, _ = _verified_admin(client, fake_email)
    headers = {"Authorization": f"Bearer {token}"}
    invitee = f"rev-{uuid.uuid4().hex[:8]}@acme.com"
    created = client.post(
        "/api/v1/invitations", json={"email": invitee, "role": "member"}, headers=headers
    ).json()
    raw = _invite_token(fake_email)
    assert client.delete(f"/api/v1/invitations/{created['id']}", headers=headers).status_code == 204
    resp = client.post(
        "/api/v1/invitations/accept",
        json={"token": raw, "password": "pw-pw-pw-pw", "full_name": "N"},
    )
    assert resp.status_code == 400


def test_member_cannot_invite(client, fake_email, db):
    from sqlalchemy import select

    from app.api.deps import invalidate_membership_cache
    from app.models.workspace import WorkspaceMembership, WorkspaceRole

    token, _ = _verified_admin(client, fake_email)
    headers = {"Authorization": f"Bearer {token}"}
    me = client.get("/api/v1/auth/me", headers=headers).json()
    membership = db.scalars(
        select(WorkspaceMembership).where(
            WorkspaceMembership.user_id == uuid.UUID(me["user_id"])
        )
    ).first()
    membership.role = WorkspaceRole.member
    db.commit()
    invalidate_membership_cache(
        uuid.UUID(me["user_id"]), uuid.UUID(me["active_workspace_id"])
    )
    resp = client.post(
        "/api/v1/invitations", json={"email": "x@acme.com", "role": "member"}, headers=headers
    )
    assert resp.status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/integration/test_invitations.py -v`
Expected: FAIL — 404 on `/api/v1/invitations`

- [ ] **Step 3: Write minimal implementation**

`backend/app/services/invitation_service.py`:

```python
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, InvalidTokenError, TokenExpiredError
from app.models.invitation import Invitation
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from app.repositories.workspace_repository import WorkspaceRepository
from app.services.token_service import generate_token, hash_token, is_expired

INVITE_TTL = timedelta(days=7)


class InvitationService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def create(
        self,
        workspace_id: uuid.UUID,
        email: str,
        role: WorkspaceRole,
        invited_by_user_id: uuid.UUID,
    ) -> tuple[Invitation, str]:
        """Returns (invitation, raw_token). Only the hash is persisted."""
        existing_user = WorkspaceRepository(self._db).get_user_by_email(email)
        if existing_user is not None:
            membership = WorkspaceRepository(self._db).get_membership(
                existing_user.id, workspace_id
            )
            if membership is not None:
                raise ConflictError(
                    "That person is already a member of this workspace",
                    code="already_member",
                )

        pending = self._db.scalars(
            select(Invitation).where(
                Invitation.workspace_id == workspace_id,
                Invitation.email == email,
                Invitation.accepted_at.is_(None),
            )
        ).first()
        if pending is not None:
            raise ConflictError(
                "An invitation is already pending for that address",
                code="invite_pending",
            )

        raw = generate_token()
        invitation = Invitation(
            workspace_id=workspace_id,
            email=email,
            role=role,
            token_hash=hash_token(raw),
            invited_by_user_id=invited_by_user_id,
            expires_at=datetime.now(UTC) + INVITE_TTL,
        )
        self._db.add(invitation)
        self._db.flush()
        return invitation, raw

    def find_valid(self, raw_token: str) -> Invitation:
        invitation = self._db.scalars(
            select(Invitation).where(Invitation.token_hash == hash_token(raw_token))
        ).first()
        if invitation is None or invitation.accepted_at is not None:
            raise InvalidTokenError("This invitation is no longer valid")
        if is_expired(invitation.expires_at):
            raise TokenExpiredError("This invitation has expired")
        return invitation

    def accept(self, invitation: Invitation, user: User) -> WorkspaceMembership:
        now = datetime.now(UTC)
        membership = WorkspaceMembership(
            workspace_id=invitation.workspace_id, user_id=user.id, role=invitation.role
        )
        self._db.add(membership)
        invitation.accepted_at = now
        # Receiving the invite at this address proves ownership of it.
        if user.email_verified_at is None:
            user.email_verified_at = now
        self._db.flush()
        return membership

    def workspace_name(self, invitation: Invitation) -> str:
        return self._db.get(Workspace, invitation.workspace_id).name
```

`backend/app/api/v1/invitations.py`:

```python
import uuid

from fastapi import APIRouter, Depends, Header, Request, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, require_admin
from app.core.audit import log_audit_event
from app.core.config import get_settings
from app.core.errors import NotFoundError, PermissionDeniedError
from app.core.rate_limit import limiter
from app.core.security import create_access_token, decode_access_token, hash_password
from app.db.session import get_db
from app.email.factory import get_email_provider
from app.email.provider import EmailProvider
from app.email.templates import invite_message
from app.models.invitation import Invitation
from app.models.user import User
from app.models.workspace import WorkspaceRole
from app.repositories.workspace_repository import WorkspaceRepository
from app.services.invitation_service import InvitationService

router = APIRouter(prefix="/invitations", tags=["invitations"])


class CreateInvitationRequest(BaseModel):
    email: EmailStr
    role: WorkspaceRole = WorkspaceRole.member


class InvitationResponse(BaseModel):
    id: str
    email: str
    role: str
    expires_at: str


class InvitationPreviewResponse(BaseModel):
    workspace_name: str
    email: str


class AcceptInvitationRequest(BaseModel):
    token: str
    password: str | None = None
    full_name: str | None = None


class AcceptInvitationResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("", response_model=InvitationResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(get_settings().RATE_LIMIT_INVITE)
def create_invitation(
    request: Request,
    payload: CreateInvitationRequest,
    current_user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
    email_provider: EmailProvider = Depends(get_email_provider),
) -> InvitationResponse:
    service = InvitationService(db)
    invitation, raw = service.create(
        current_user.workspace_id, payload.email, payload.role, current_user.user_id
    )
    inviter = db.get(User, current_user.user_id)
    link = f"{get_settings().FRONTEND_BASE_URL}/invite/accept?token={raw}"
    email_provider.send(
        invite_message(payload.email, service.workspace_name(invitation), inviter.email, link)
    )
    db.commit()
    log_audit_event(
        "invitation.created",
        actor_user_id=str(current_user.user_id),
        workspace_id=str(current_user.workspace_id),
        email=payload.email,
    )
    return InvitationResponse(
        id=str(invitation.id),
        email=invitation.email,
        role=invitation.role.value,
        expires_at=invitation.expires_at.isoformat(),
    )


@router.get("", response_model=list[InvitationResponse])
def list_invitations(
    current_user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)
) -> list[InvitationResponse]:
    invitations = db.scalars(
        select(Invitation).where(
            Invitation.workspace_id == current_user.workspace_id,
            Invitation.accepted_at.is_(None),
        )
    ).all()
    return [
        InvitationResponse(
            id=str(i.id), email=i.email, role=i.role.value, expires_at=i.expires_at.isoformat()
        )
        for i in invitations
    ]


@router.delete("/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_invitation(
    invitation_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> None:
    invitation = db.get(Invitation, invitation_id)
    if invitation is None or invitation.workspace_id != current_user.workspace_id:
        raise NotFoundError("Invitation not found")
    db.delete(invitation)
    db.commit()
    log_audit_event(
        "invitation.revoked",
        actor_user_id=str(current_user.user_id),
        workspace_id=str(current_user.workspace_id),
    )


@router.get("/preview", response_model=InvitationPreviewResponse)
def preview_invitation(
    token: str, db: Session = Depends(get_db)
) -> InvitationPreviewResponse:
    """Unauthenticated so the accept page can name the workspace before the
    invitee has an account. Reveals only the workspace name and the address
    the invite was already sent to."""
    service = InvitationService(db)
    invitation = service.find_valid(token)
    return InvitationPreviewResponse(
        workspace_name=service.workspace_name(invitation), email=invitation.email
    )


@router.post("/accept", response_model=AcceptInvitationResponse)
def accept_invitation(
    payload: AcceptInvitationRequest,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> AcceptInvitationResponse:
    """Authorization is optional: an invitee with no account posts a password
    instead. When a session *is* present it must belong to the invited
    address, otherwise the membership would silently attach to the wrong
    account."""
    service = InvitationService(db)
    invitation = service.find_valid(payload.token)

    if authorization and authorization.startswith("Bearer "):
        try:
            claims = decode_access_token(authorization.removeprefix("Bearer "))
        except Exception:
            claims = None
        if claims is not None:
            session_user = db.get(User, uuid.UUID(claims["sub"]))
            if session_user is not None and session_user.email != invitation.email:
                raise PermissionDeniedError(
                    "This invitation was sent to a different email address",
                    code="invite_email_mismatch",
                )

    user = WorkspaceRepository(db).get_user_by_email(invitation.email)
    if user is None:
        if not payload.password:
            raise PermissionDeniedError(
                "A password is required to create your account", code="password_required"
            )
        user = User(
            email=invitation.email,
            hashed_password=hash_password(payload.password),
            full_name=payload.full_name,
        )
        db.add(user)
        db.flush()

    service.accept(invitation, user)
    db.commit()
    log_audit_event(
        "invitation.accepted",
        user_id=str(user.id),
        workspace_id=str(invitation.workspace_id),
    )
    return AcceptInvitationResponse(
        access_token=create_access_token(user.id, invitation.workspace_id)
    )
```

> **Route ordering:** register `/preview` before any `/{invitation_id}` route, or FastAPI will try to parse `preview` as a UUID.

Register the router in `backend/app/api/v1/router.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/integration/test_invitations.py -v`
Expected: PASS

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && pytest -v`
Expected: PASS — the backend half of 1a is now complete.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/invitation_service.py backend/app/api/v1/invitations.py backend/app/api/v1/router.py backend/tests/integration/test_invitations.py
git commit -m "feat: add workspace invitations with auto-verification on accept"
```

---

### Task 12: Frontend auth context and route guards

**Files:**
- Create: `frontend/src/app/AuthContext.tsx`, `frontend/src/app/guards.tsx`
- Modify: `frontend/src/lib/apiClient.ts`, `frontend/src/app/routes.tsx`
- Test: manual (this repo has no frontend test runner configured; do not add one in this task)

**Interfaces:**
- Consumes: `GET /api/v1/auth/me`, `POST /api/v1/auth/switch-workspace`
- Produces: `useAuth()` returning `{me, loading, refresh, login, logout, switchWorkspace}`; `<RequireAuth>`, `<RequireVerified>`, `<RequireAdmin>`; `ApiError` with `.code`

- [ ] **Step 1: Propagate the error `code` through the API client**

In `frontend/src/lib/apiClient.ts`, ensure thrown errors carry the backend `code`:

```ts
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string | null,
  ) {
    super(message)
  }
}
```

In the response handler, parse the body and throw `new ApiError(body.detail ?? 'Request failed', response.status, body.code ?? null)`.

- [ ] **Step 2: Write the auth context**

```tsx
// frontend/src/app/AuthContext.tsx
import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { apiFetch, clearStoredToken, getStoredToken, setStoredToken } from '@/lib/apiClient'

export interface WorkspaceSummary {
  id: string
  name: string
  slug: string
  role: 'admin' | 'member'
}

export interface Me {
  user_id: string
  email: string
  full_name: string | null
  email_verified: boolean
  active_workspace_id: string
  role: 'admin' | 'member'
  workspaces: WorkspaceSummary[]
}

interface AuthValue {
  me: Me | null
  loading: boolean
  refresh: () => Promise<void>
  login: (token: string) => Promise<void>
  logout: () => void
  switchWorkspace: (workspaceId: string) => Promise<void>
}

const AuthContext = createContext<AuthValue | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [me, setMe] = useState<Me | null>(null)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    if (!getStoredToken()) {
      setMe(null)
      setLoading(false)
      return
    }
    try {
      setMe(await apiFetch<Me>('/api/v1/auth/me'))
    } catch {
      clearStoredToken()
      setMe(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const login = useCallback(
    async (token: string) => {
      setStoredToken(token)
      setLoading(true)
      await refresh()
    },
    [refresh],
  )

  const logout = useCallback(() => {
    clearStoredToken()
    setMe(null)
  }, [])

  const switchWorkspace = useCallback(
    async (workspaceId: string) => {
      const { access_token } = await apiFetch<{ access_token: string }>(
        '/api/v1/auth/switch-workspace',
        { method: 'POST', body: JSON.stringify({ workspace_id: workspaceId }) },
      )
      await login(access_token)
    },
    [login],
  )

  return (
    <AuthContext.Provider value={{ me, loading, refresh, login, logout, switchWorkspace }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used inside AuthProvider')
  return value
}
```

- [ ] **Step 3: Write the guards**

```tsx
// frontend/src/app/guards.tsx
import { Navigate } from 'react-router-dom'
import { useAuth } from './AuthContext'

export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { me, loading } = useAuth()
  if (loading) return <div className="p-8 text-sm text-slate-500">Loading…</div>
  if (!me) return <Navigate to="/login" replace />
  return <>{children}</>
}

export function RequireVerified({ children }: { children: React.ReactNode }) {
  const { me, loading } = useAuth()
  if (loading) return <div className="p-8 text-sm text-slate-500">Loading…</div>
  if (!me) return <Navigate to="/login" replace />
  if (!me.email_verified) return <Navigate to="/verify-email" replace />
  return <>{children}</>
}

export function RequireAdmin({ children }: { children: React.ReactNode }) {
  const { me, loading } = useAuth()
  if (loading) return <div className="p-8 text-sm text-slate-500">Loading…</div>
  if (!me) return <Navigate to="/login" replace />
  if (me.role !== 'admin') return <Navigate to="/chat" replace />
  return <>{children}</>
}
```

- [ ] **Step 4: Wire the provider and guards into routing**

Wrap the router in `<AuthProvider>` (in `App.tsx`), replace the local `RequireAuth` in `routes.tsx` with the imported guards, and wrap `AppShell` in `RequireVerified` so unverified users are pushed to `/verify-email`.

- [ ] **Step 5: Verify in the browser**

Run: `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d frontend backend`
Then: sign up at `http://localhost:5173/signup`, confirm you are redirected to the verify screen, copy the link from `docker compose logs backend`, and confirm you land in chat after verifying.
Expected: redirect on unverified, chat reachable after verification.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/AuthContext.tsx frontend/src/app/guards.tsx frontend/src/app/routes.tsx frontend/src/app/App.tsx frontend/src/lib/apiClient.ts
git commit -m "feat: add frontend auth context and route guards"
```

---

### Task 13: Signup, verification, and password reset pages

**Files:**
- Create: `frontend/src/features/auth/SignupPage.tsx`, `VerifyEmailPage.tsx`, `ForgotPasswordPage.tsx`, `ResetPasswordPage.tsx`
- Modify: `frontend/src/app/routes.tsx`, `frontend/src/features/auth/LoginPage.tsx`

**Interfaces:**
- Consumes: `POST /auth/signup`, `/verify-email`, `/resend-verification`, `/forgot-password`, `/reset-password`; `useAuth().login`
- Produces: routes `/signup`, `/verify-email`, `/forgot-password`, `/reset-password`

- [ ] **Step 1: Build the signup page**

Match `LoginPage.tsx`'s existing markup and Tailwind classes. Fields: `full_name`, `email`, `password`, `workspace_name`. On submit `POST /api/v1/auth/signup`, then `await login(access_token)`, then `navigate('/verify-email')`. On `ApiError` with `code === 'email_taken'`, show "An account with that email already exists" and link to `/login`.

- [ ] **Step 2: Build the verify-email page**

Two modes in one component:
- With `?token=` in the URL: `POST /api/v1/auth/verify-email` on mount, then `await refresh()` and `navigate('/chat')` on success. On failure show the message and a "request a new link" button.
- Without a token: show "We sent a link to {me.email}" plus a resend button calling `POST /api/v1/auth/resend-verification`. Always show the same confirmation after resending — never reveal whether the address exists.

- [ ] **Step 3: Build forgot-password and reset-password pages**

`/forgot-password`: email field → `POST /api/v1/auth/forgot-password` → always render "If an account exists for that address, we've sent a reset link." regardless of the response. Do not branch on the result.

`/reset-password`: reads `?token=`, takes a new password, `POST /api/v1/auth/reset-password`, then redirects to `/login` with a success banner. On `code === 'token_expired'` offer a link back to `/forgot-password`.

- [ ] **Step 4: Link them from the login page**

Add "Create an account" → `/signup` and "Forgot your password?" → `/forgot-password` to `LoginPage.tsx`.

- [ ] **Step 5: Register the routes**

Add all four as public routes in `routes.tsx`, outside `RequireAuth`.

- [ ] **Step 6: Verify the full flow in the browser**

Sign up → land on verify screen → copy link from `docker compose logs backend` → verify → reach chat. Then log out, use forgot-password, copy that link, reset, and log in with the new password.
Expected: both flows complete without touching the database by hand.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/auth frontend/src/app/routes.tsx
git commit -m "feat: add signup, verification, and password reset pages"
```

---

### Task 14: Invite acceptance page

**Files:**
- Create: `frontend/src/features/invites/AcceptInvitePage.tsx`
- Modify: `frontend/src/app/routes.tsx`

**Interfaces:**
- Consumes: `GET /api/v1/invitations/preview?token=`, `POST /api/v1/invitations/accept`
- Produces: public route `/invite/accept`

- [ ] **Step 1: Build the page**

On mount, read `?token=` and call the preview endpoint. Render "You've been invited to join **{workspace_name}**" with the invited email shown read-only and non-editable — the backend binds the membership to the invited address, so an editable field would mislead.

If `useAuth().me` is null, show password + full name fields and post `{token, password, full_name}`. If a session already exists, show only an "Accept invitation" button and post `{token}`.

On success, `await login(access_token)` and navigate to `/chat`.

- [ ] **Step 2: Handle the failure states explicitly**

- `code === 'invalid_token'` → "This invitation is no longer valid. Ask your workspace admin to send a new one."
- `code === 'token_expired'` → "This invitation has expired." plus the same guidance.
- `code === 'already_member'` → "You're already in this workspace." with a link to `/chat`.

- [ ] **Step 3: Register the route**

Add `/invite/accept` as a public route, outside `RequireAuth`.

- [ ] **Step 4: Verify end to end**

As an admin, invite a fresh address; copy the link from `docker compose logs backend`; open it in a private window; set a password; confirm you land in chat as a `member` and that `/settings/members` is not reachable.
Expected: the new user is verified without a separate verification email.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/invites frontend/src/app/routes.tsx
git commit -m "feat: add invite acceptance page"
```

---

### Task 15: Settings — workspace and members

**Files:**
- Create: `frontend/src/features/settings/WorkspaceSettingsPage.tsx`, `frontend/src/features/settings/MembersPage.tsx`
- Modify: `frontend/src/app/routes.tsx`, `frontend/src/app/AppShell.tsx`

**Interfaces:**
- Consumes: `PATCH /workspaces/current`, `GET /workspaces/current/members`, `PATCH`/`DELETE .../members/{user_id}`, `GET`/`POST`/`DELETE /invitations`
- Produces: admin-only routes `/settings/workspace`, `/settings/members`

- [ ] **Step 1: Build the workspace settings page**

A single "Workspace name" field with a Save button calling `PATCH /api/v1/workspaces/current`, then `await refresh()` so the switcher label updates immediately.

- [ ] **Step 2: Build the members page**

Two sections, reusing the existing `card`, `button`, `badge`, `input` components in `components/ui/`:

- **Members** — email, name, role badge, a role dropdown (`admin`/`member`), and a Remove button. On a 409 with `code === 'last_admin'`, surface "A workspace must keep at least one admin" inline rather than as a generic failure.
- **Pending invitations** — email, role, expiry, and Revoke. Above it, an invite form (email + role) calling `POST /api/v1/invitations`. On `code === 'already_member'` or `'invite_pending'`, show the message inline against the email field.

Refresh both lists after every mutation.

- [ ] **Step 3: Register the routes behind RequireAdmin**

Nest both under `AppShell` wrapped in `<RequireAdmin>`.

- [ ] **Step 4: Add navigation**

In `AppShell.tsx`, show a Settings link only when `me.role === 'admin'`.

- [ ] **Step 5: Verify both roles in the browser**

As admin: invite someone, change their role, remove them, and confirm demoting yourself as the only admin is refused with the inline message. Then, as the invited member, confirm `/settings/members` redirects to `/chat` and the Settings link is absent.
Expected: enforcement holds in the UI and at the API.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/settings frontend/src/app/routes.tsx frontend/src/app/AppShell.tsx
git commit -m "feat: add workspace and member settings pages"
```

---

### Task 16: Workspace switcher

**Files:**
- Create: `frontend/src/components/WorkspaceSwitcher.tsx`
- Modify: `frontend/src/app/AppShell.tsx`

**Interfaces:**
- Consumes: `useAuth().me.workspaces`, `useAuth().switchWorkspace`
- Produces: `<WorkspaceSwitcher />`

- [ ] **Step 1: Build the component**

Render the active workspace name as a dropdown listing `me.workspaces`. Selecting one calls `switchWorkspace(id)`, which mints a new token and re-fetches `/auth/me`. Then `navigate('/chat')` — staying on a document page would show a document from the previous tenant.

If `me.workspaces.length === 1`, render the name as plain text with no dropdown.

Add a "Create workspace" item at the bottom that prompts for a name and calls `POST /api/v1/workspaces`, then switches into it.

- [ ] **Step 2: Mount it in the shell**

Place it in the `AppShell` header, left of the existing nav.

- [ ] **Step 3: Verify tenant separation across a switch**

Create a second workspace, switch into it, and confirm the document list is empty and chat retrieves nothing from the first workspace.
Expected: no cross-tenant leakage — this is the visible counterpart to `test_switched_token_cannot_read_the_other_workspaces_documents`.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/WorkspaceSwitcher.tsx frontend/src/app/AppShell.tsx
git commit -m "feat: add workspace switcher"
```

---

### Task 17: Retire the seed script

Per the spec, `seed_dev_data.py` is deleted in the same change that lands signup — not before, since it is currently the only way a user exists.

**Files:**
- Delete: `backend/app/seed/seed_dev_data.py`, `backend/app/seed/__init__.py`
- Modify: `README.md`, `backend/tests/integration/conftest.py`
- Test: `backend/tests/integration/test_no_seed_dependency.py`

**Interfaces:**
- Consumes: the signup endpoint from Task 6
- Produces: nothing — this task removes surface area

- [ ] **Step 1: Confirm nothing imports the seed**

Run: `cd backend && grep -rn "seed_dev_data" --include='*.py' --include='*.md' --include='*.yml' . ..`
Expected: hits only in the files listed above. If application code imports it, stop and reassess — that is a dependency the spec did not anticipate.

- [ ] **Step 2: Write the test that replaces it**

```python
# backend/tests/integration/test_no_seed_dependency.py
import re
import uuid

import pytest

from app.email.factory import get_email_provider
from app.email.provider import FakeEmailProvider
from app.main import app


@pytest.fixture
def fake_email():
    provider = FakeEmailProvider()
    app.dependency_overrides[get_email_provider] = lambda: provider
    yield provider
    app.dependency_overrides.pop(get_email_provider, None)


def test_a_usable_account_can_be_created_without_the_seed(client, fake_email):
    """The seed script is gone; signup must be sufficient to reach the app."""
    email = f"fresh-{uuid.uuid4().hex[:8]}@acme.com"
    token = client.post(
        "/api/v1/auth/signup",
        json={
            "email": email,
            "password": "pw-pw-pw-pw",
            "full_name": "Fresh User",
            "workspace_name": "Fresh Co",
        },
    ).json()["access_token"]
    raw = re.search(r"token=([A-Za-z0-9_\-]+)", fake_email.sent[-1].text).group(1)
    client.post("/api/v1/auth/verify-email", json={"token": raw})

    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/v1/documents", headers=headers).status_code == 200
    assert client.get("/api/v1/auth/me", headers=headers).json()["role"] == "admin"
```

- [ ] **Step 3: Delete the seed and update the docs**

Remove `backend/app/seed/`. In `README.md`, replace any seeded-credential instructions with: create an account at `http://localhost:5173/signup`, then copy the verification link from `docker compose logs backend` (the console email provider prints it).

Leave `backend/tests/integration/conftest.py`'s `make_workspace` helper in place — it builds fixtures directly and does not use the seed.

- [ ] **Step 4: Run the full suite**

Run: `cd backend && pytest -v`
Expected: PASS with no import errors from the removed module.

- [ ] **Step 5: Verify a cold start from an empty database**

Run:
```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml down -v
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```
Then sign up through the UI and reach chat.
Expected: a brand-new database yields a usable account with no manual SQL and no seed script. This is the acceptance test for the whole sub-project.

- [ ] **Step 6: Commit**

```bash
git rm -r backend/app/seed
git add README.md backend/tests/integration/test_no_seed_dependency.py
git commit -m "refactor: retire seed script now that signup exists"
```

---

## Definition of Done

- [ ] A stranger can sign up, verify, and reach chat with no manual database access
- [ ] An admin can invite a teammate who joins without a separate verification step
- [ ] `member` callers are refused on every admin endpoint (403 `admin_required`)
- [ ] Removing a member revokes their access within 60 seconds
- [ ] A user in two workspaces can switch, and sees no data from the other
- [ ] `forgot-password` responds identically for known and unknown addresses
- [ ] `docker compose up` still needs zero email credentials
- [ ] `pytest` passes, including the pre-existing `test_permission_isolation.py`
- [ ] `seed_dev_data.py` is gone

## Deferred to 1b

Refresh tokens, sessions table, TOTP MFA with recovery codes, trusted devices, GeoIP, impossible-travel detection, active-session UI with remote revoke. 1a keeps the 24-hour access token; the per-request membership re-check is what makes that acceptable in the meantime.

**Accepted gap:** no CAPTCHA on signup (see the spec's Risks section for the revisit triggers).
