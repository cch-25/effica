# API contract changelog

## 1.0.1 - 2026-08-19

- Changed: `/api/v1/auth/providers` exposes Google as the only production sign-in provider.
- Changed: OAuth start/callback paths reject unsupported providers; the mock adapter is test-only.
- Changed: cancelled Google authorization returns safely to the login page without creating a session.
- Removed: Kakao and Naver from the executable public authentication contract.

## 1.0.0 - 2026-08-16

- Added: the complete `/api/v1` public, member, analyst, reviewer and admin contract from the
  master specification, plus `/health/live` and `/health/ready`.
- Added: stable error envelopes, cursor parameters, CSRF/session security schemes,
  `Idempotency-Key`, and `If-Match` concurrency conditions.
- Changed: none.
- Deprecated: none.
- Removed: none.
- MAS_A impact: generate the web client from `openapi.json`; use the documented role, CSRF,
  idempotency and version headers. No web-owned file was changed.
