# Tenancy & Onboarding (Sub-project 1a) — Design

**Date:** 2026-08-15
**Status:** Approved for planning
**Scope:** Turn the existing single-tenant RAG vertical slice into a product real
customers can sign up for, invite their team into, and administer.

## Context

The repo today is Milestone 1: a working permission-aware RAG pipeline behind a
login page. Verified state of the codebase at design time:

- **Auth** is `POST /api/v1/auth/login` and nothing else. No signup, no
  verification, no reset, no invites.
- **Workspaces** exist as models (`Workspace`, `WorkspaceMembership`,
  `WorkspaceRole`) with no API to create, join, or manage one.
- **Roles** (`admin`/`member`) are defined and enforced nowhere. The only
  reference in the backend outside the model file is the seed script assigning
  `admin`.
- **Frontend** is three pages: Login, Chat, Documents.
- **Email infrastructure** does not exist.

The load-bearing good news: **tenant isolation is already structurally sound.**
Every read path scopes by workspace — `documents` via
`repo.list_documents(current_user.workspace_id)`, document content via an
explicit cross-workspace check that logs violations
(`services/document_access_service.py:26`), retrieval, and the Qdrant payload
schema carrying `workspace_id` + `allowed_roles`. This design deliberately
preserves that layer untouched.

### The decision this sub-project exists to serve

The product targets **external customers on paid plans** — many companies, each
isolated, eventually billed. Nothing else in the roadmap matters until a
customer can come into existence without a developer running SQL.

## Goals

1. A stranger can sign up, verify their email, and land in their own workspace.
2. That person can invite teammates, who join without manual intervention.
3. `admin` vs `member` is enforced at the API, not just recorded.
4. One user can belong to several workspaces and switch between them.
5. Removing someone from a workspace revokes their access in under a minute
   rather than up to 24 hours.

## Non-goals (deferred to 1b and later sub-projects)

Explicitly out of scope, recorded so nothing is assumed lost:

- **1b — Sessions, MFA & adaptive security:** refresh tokens, sessions table,
  TOTP MFA with recovery codes, trusted devices, GeoIP, impossible-travel
  detection, active-session UI with remote revoke.
- **2 — Connector UI:** connecting Drive/Gmail in-app rather than by curl.
- **3 — Billing & plans.**
- **4 — Production readiness:** domain, TLS, Google OAuth verification review,
  per-workspace quotas.

1a keeps the current single 24-hour access token. The membership re-check
(below) is what makes that acceptable until 1b lands.

## Retiring the demo path

The seeded demo user is **not** being repaired. It is superseded by signup and
is deleted as part of this sub-project.

For the record, so nobody re-diagnoses it: migration `0003` added `user_id` to
`connector_accounts` and `_trigger_sync` (`api/v1/connectors.py:47`) filters on
it, but `seed_dev_data.py` was never updated to set it. The seeded mock
connector therefore has `user_id = NULL`, which never matches, so
`POST /connectors/google-drive/sync` returns 404 and no document can be
ingested through the demo path. **This is known-broken and intentionally left
that way.**

Sequencing: `seed_dev_data.py` stays in the tree until signup works end to end,
because it is currently the only way a user exists and deleting it early would
leave no way to log in locally. It is deleted in the same change that lands
signup — not before, not after.

Mock connectors are unaffected and stay. They are what allows local development
and CI to run without Google credentials.

## Architecture

### Email delivery

Mirrors the existing swappable-provider pattern in `app/ai/` (local vs Mistral,
selected by `AI_PROVIDER`) rather than introducing a second style:

```
app/email/
  provider.py      EmailProvider protocol: send(to, subject, text, html)
  console.py       ConsoleEmailProvider — logs to stdout (dev default)
  resend.py        ResendEmailProvider — production
  templates/       verify_email, invite, password_reset (text + minimal HTML)
```

Selected by a new `EMAIL_PROVIDER` setting alongside `AI_PROVIDER`, defaulting
to `console` in dev. **Local development requires no email account** — invite
and reset links print to the backend logs, so `docker compose up` keeps working
with zero external credentials.

Production provider is **Resend** (confirmed). The abstraction keeps that a
one-file decision if it ever needs revisiting.

### New modules

Following the existing `api/v1` + `services/` split:

- `services/tenancy_service.py` — workspace creation, membership management
- `services/invitation_service.py` — issue, accept, revoke invites
- `api/v1/workspaces.py`, `api/v1/invitations.py`, extensions to `auth.py`
- `api/deps.py` — `require_admin` dependency, membership re-check

## Data model

### New tables

**`invitations`**

| Column | Notes |
|---|---|
| `id` | uuid pk |
| `workspace_id` | fk workspaces |
| `email` | invitee address |
| `role` | `admin` \| `member` |
| `token_hash` | SHA-256 of the raw token |
| `invited_by_user_id` | fk users |
| `expires_at` | issued + 7 days |
| `accepted_at` | nullable |

Partial unique index on `(workspace_id, email) WHERE accepted_at IS NULL` — no
duplicate pending invites, but re-inviting someone who left is allowed.

**`auth_tokens`** — one table rather than two near-identical ones:

| Column | Notes |
|---|---|
| `id` | uuid pk |
| `user_id` | fk users |
| `purpose` | enum: `verify_email` \| `password_reset` |
| `token_hash` | SHA-256 of the raw token |
| `expires_at` | verify: 7 days; reset: 1 hour |
| `used_at` | nullable, single-use enforcement |

### Changed tables

- `users` gains `email_verified_at` (nullable timestamptz) and `full_name`.

### Token storage

Tokens are stored **hashed (SHA-256), never in plaintext**. The raw token exists
only inside the emailed link. A database read — backup leak, SQL injection, a
curious employee — therefore cannot be converted into account takeover. Costs
nothing now; impossible to retrofit once links are in the wild.

Migrations extend the existing Alembic chain: `0003` → `0004`.

## Auth flows

### Multi-workspace token model

Login stops implying a workspace, but the **token keeps carrying one**.
`POST /auth/switch-workspace` returns a fresh token scoped to a different
workspace.

This is the central decision: every existing endpoint — documents, chat,
retrieval, Qdrant payload filtering — reads `current_user.workspace_id` and is
already correctly scoped. Keeping the workspace inside the token means the
entire isolation layer stays untouched. No endpoint changes, no re-indexing.

### Signup

Creates user (unverified) + workspace + admin membership in a single
transaction, then sends the verification email. Unverified users can log in,
but `get_current_user` rejects workspace-scoped calls with
`EmailNotVerifiedError` (a distinguishable code) so the frontend routes to a
"check your email" screen rather than a dead end.

Precisely, an unverified user is **allowed**: `GET /auth/me`,
`POST /auth/verify-email`, `POST /auth/resend-verification`,
`GET /workspaces`, `POST /auth/switch-workspace`, and
`POST /invitations/accept`. Everything else — documents, chat, connectors,
`/workspaces/current*`, and invitation management — is rejected.

Workspace slug is generated from the workspace name and uniqueness-checked with
a numeric suffix on collision.

### Invite acceptance

Receiving an invite at an address proves ownership of it, so **accepting an
invite sets `email_verified_at` directly** — an invited teammate never sees a
separate verification step.

- *No account yet* → link opens signup with email prefilled and locked
- *Account exists* → link opens login, then creates the membership

Edge cases, resolved explicitly:

- **Invitee is already a member** of that workspace → `POST /invitations`
  returns 409 `already_member`; no email is sent.
- **Invite accepted by a logged-in user whose email differs** from the invited
  address → rejected with 403 `invite_email_mismatch`, rather than silently
  attaching the membership to the wrong account.
- **Expired or already-accepted token** → `TokenExpiredError` / 409, with the
  UI offering to request a fresh invite.

### Membership re-check

`get_current_user` (`api/deps.py:24`) currently trusts `workspace_id` from a
24-hour-old JWT and never verifies membership. It gains a DB session and checks
that the `(user_id, workspace_id)` membership exists and the user is active.

Cached in Redis (already running) with a **60-second TTL**, keyed by
`user_id:workspace_id`, invalidated immediately on membership change. Worst
case a removed user retains access for 60 seconds, versus 24 hours today.

### Role enforcement

A `require_admin` dependency gates: invites (create/revoke), member removal and
role changes, connector connect/disconnect, and workspace settings. Members
keep chat, documents, and syncing their own connectors.

Role set stays `admin`/`member` deliberately — the Qdrant payloads written at
ingestion (`workers/tasks_ingestion.py:63`) already carry exactly these two
values, so no re-indexing is required.

## API surface

```
auth.py          POST /signup  ·  /verify-email  ·  /resend-verification
                 POST /forgot-password  ·  /reset-password  ·  /switch-workspace
                 POST /login (extended: also returns the user's workspaces)
                 GET  /me     (user + memberships + active workspace + role)

workspaces.py    GET  /workspaces                       my memberships
                 POST /workspaces                       create another
                 GET/PATCH /workspaces/current          rename = admin
                 GET  /workspaces/current/members
                 PATCH/DELETE .../members/{user_id}     admin only

invitations.py   POST/GET/DELETE /invitations           admin only
                 GET  /invitations/preview?token=       public: workspace name
                 POST /invitations/accept
```

### Safeguards

- **Enumeration resistance** — `forgot-password` returns an identical 200 for
  known and unknown addresses, so it cannot be used to discover customers.
- **Last-admin protection** — removing or demoting the final admin of a
  workspace returns 409 rather than orphaning a workspace with a live
  subscription.
- **Rate limits** on signup, invite, and password reset, reusing the `slowapi`
  pattern already configured for `RATE_LIMIT_LOGIN` (`5/minute`).
- **Invite expiry** — 7 days, revocable before acceptance.

## Frontend

New pages, added to the existing three:

```
/signup              /verify-email?token=      /invite/accept?token=
/forgot-password     /reset-password?token=
/settings/workspace  (admin: rename)
/settings/members    (admin: list, invite, change role, remove)
```

Plus a workspace switcher in `AppShell`.

`RequireAuth` in `routes.tsx` currently only checks that a token exists in
localStorage — there is no notion of who the user is. It is replaced by three
guards: `RequireAuth`, `RequireVerified`, `RequireAdmin`, backed by an auth
context hydrated from `GET /auth/me` on load.

Authorization decisions are read from the API, not decoded from the JWT in the
browser.

## Error handling

`core/errors.py` returns `{"detail": message}` with no machine-readable code.
The frontend must distinguish "email not verified" from an ordinary 403 to
route correctly, and string-matching messages is brittle.

Add an optional `code` field to `AppError` and the exception handler —
backwards compatible, no existing call site changes. New error types:

| Error | Status | Code |
|---|---|---|
| `EmailNotVerifiedError` | 403 | `email_not_verified` |
| `InvalidTokenError` | 400 | `invalid_token` |
| `TokenExpiredError` | 400 | `token_expired` |
| last admin (reuses `ConflictError`) | 409 | `last_admin` |
| already a member (reuses `ConflictError`) | 409 | `already_member` |
| invite email mismatch (reuses `PermissionDeniedError`) | 403 | `invite_email_mismatch` |

## Testing

Test-first, following the existing `tests/{unit,integration}` split.

**Unit:** token hash/verify round-trip, invite expiry, last-admin rule, role
checks, slug generation and collision handling.

**Integration:** signup → verify → login; invite → accept for both paths (new
user and existing user); password reset; workspace switch issues a correctly
scoped token.

**Security-critical — not shippable without these:**

- A user in workspace A cannot read workspace B's documents after switching
- A removed member loses access once the cache TTL lapses
- Admin-only endpoints reject `member` callers
- `forgot-password` returns identical responses for known and unknown addresses

A `FakeEmailProvider` records sends so tests can assert on the actual link
tokens rather than mocking at the transport layer.

## Risks

- **Membership re-check adds a DB read to every authenticated request.** Redis
  caching mitigates it, but the cache invalidation path on membership change
  must be correct or removals silently fail to take effect. Covered by an
  explicit integration test.
- **Email deliverability** is a production concern the console provider hides
  during development. Domain verification and SPF/DKIM belong to sub-project 4,
  but should not be discovered late.
- **Open self-serve signup invites abuse.** Rate limits and email verification
  are the mitigation in 1a; if it proves insufficient, CAPTCHA is the next
  lever and is not designed here.
