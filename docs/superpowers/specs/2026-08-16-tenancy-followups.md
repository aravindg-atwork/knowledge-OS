# Tenancy (1a) — carried-forward follow-ups

Triaged at the final whole-branch review of `feat/tenancy-onboarding`
(2026-08-16). Nothing here blocked merge; everything here is real.

## Do first in 1b

- **Password reset does not invalidate existing JWTs.** Tokens are stateless
  and nothing revokes them, so a reset does not end an attacker's session —
  and they also retain `switch-workspace` across every workspace the account
  belongs to. The spec deliberately deferred session revocation to 1b; this is
  the reason 1b's first task should be the sessions table.
  **One-line mitigation available now:** cut `JWT_EXPIRE_MINUTES` from 1440 to
  ~120. Not applied — it is a security/UX tradeoff the product owner should
  choose, since it means more frequent logins until 1b lands.

## Should fix soon

- `/reset-password` and `/verify-email` are the only token-consuming endpoints
  with no rate limit (`login`, `signup`, `forgot-password`, `/invitations/preview`
  all have one). Token entropy is 256-bit so brute force is impractical, but the
  asymmetry is unintentional.
- `/invitations/accept` reuses `RATE_LIMIT_INVITE_PREVIEW`. Accept creates
  accounts and is a higher-value target than a read-only preview; give it its
  own setting.
- Repeated `resend-verification` issues new `AuthToken` rows without
  invalidating prior unexpired ones, so several valid verification tokens can
  coexist per user.
- A malformed value in the Redis membership cache raises an uncaught
  `ValueError` → 500. It fails *closed*, so it is ugly rather than dangerous,
  but it should be caught and treated as a cache miss.
- `token_hash` carries both `unique=True` and an explicit `create_index` on
  `auth_tokens` and `invitations`. Postgres already indexes a UNIQUE
  constraint, so the second index is redundant write overhead. Drop in `0006`.
- `login` picks a membership with no `ORDER BY`, so a multi-workspace user's
  landing workspace is non-deterministic; it also never checks `is_active`.

## Accepted as-is

- **No CAPTCHA on signup** (decided 2026-08-15). Rate limits plus email
  verification are the only mitigations. Exposure is junk workspaces and
  unrequested verification email harming sending reputation — deliverability,
  not tenant isolation. Revisit on signup volume outpacing conversion, rising
  bounces/complaints, or a Resend reputation warning.
- Timing side-channels on `forgot-password` and `resend-verification` (real
  work happens only on the branch where the address exists). The response body
  and status are identical; only latency differs.
- `find_valid` distinguishes expired from invalid invitations. This is a
  deliberate UX choice — an expired invite should tell the user to request a
  new one — at the cost of a small oracle for a brute-forcer.
- `is_active` is not re-read within the 60s membership-cache window, matching
  the removal semantics already accepted for role changes.
- Minor UI: `MembersPage` shares one error slot between role-change and remove
  on the same row; `ResetPasswordPage` renders the form under a missing-token
  error; README says "log in and start chatting" though the verify link
  auto-redirects to `/chat`.

## Pre-existing, outside this feature's scope

Found while reviewing but not introduced by it, and not fixed:

- `document_repository.get_or_create_document` is check-then-act. It is guarded
  by `uq_connector_external_id`, but `tasks_ingestion.py`'s bare
  `except Exception` then calls `db.commit()` on an aborted transaction, so a
  raced file is silently dropped rather than retried.
- `next_version_number` is `max+1`, with the same race shape.
- **`docker compose up -d` fails on a cold start**: the frontend's health-gated
  dependency races the backend's healthcheck while the embedding model
  downloads, leaving the frontend uncreated. Anyone cloning the repo hits this
  on first run.
- `README.md` lines ~116-140 contain a pasted terminal fragment about a
  "Qdrant race fix" that is not documentation and should be deleted.

## Known-good, verified at final review

Recorded so it is not re-litigated: tenant isolation was traced end to end
(JWT → `get_current_user` → repositories → Qdrant filters) with no bypass;
Celery derives workspace server-side from the account row, never from task
args; the OAuth callback is authorised by a signed, purpose-tagged,
10-minute state token and now re-checks membership before writing anything.
