# API contract changelog

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
