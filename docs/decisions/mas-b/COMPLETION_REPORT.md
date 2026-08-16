# MAS_B completion report

- Date: 2026-08-16 (Asia/Seoul)
- Integration base: `main` at `fc7bbecaf60e5365dbf1da991f367099f755dd94`
- Deployment boundary: local implementation only; EC2 was not accessed or changed.

## Delivered scope

- Implemented all 69 specified FastAPI operations. No specified endpoint is left as a stub or
  intentionally unimplemented.
- All data-bearing public, member, analyst, reviewer, and admin operations select the MariaDB
  repository when `APP_BACKEND=mariadb`; `APP_BACKEND=memory` remains the explicit offline demo.
- Implemented opaque hashed sessions, CSRF binding, OAuth adapters and mock OAuth, versioned
  consent, encrypted questionnaire responses, demographics, data export, and deletion.
- Implemented source policies, canonicalization/versioning, issue membership, three-provider
  analysis, ensemble/scoring, revisioned votes, behavioral profiles, ranked feeds, read sessions,
  immutable credits, efficacy, visualization data, share PNG/BLOB lifecycle, and Auto Pilot.
- Implemented the MariaDB-only queue with leases, heartbeats, retry/backoff/jitter, `SKIP LOCKED`
  capability detection and conditional-update fallback, all 12 handler types, durable replay
  protection, and transactional result application before `SUCCEEDED`.
- Wired identifier-only jobs to MariaDB lookups for sources, article bodies, votes, scoring
  evidence, weights, recommendations, share cards, exports, and deletion policy; live crawl mode
  now performs bounded fetch/parse/retention while fixture mode remains network-free.
- Implemented durable admin idempotency and audit, optimistic `If-Match`, reviewer approval,
  completed 7/30 simulation evidence, atomic publish, and immutable rollback revisions.

## Contract and schema

- OpenAPI operations: 69
- OpenAPI SHA-256: `2462aa85ee28c23e30d1743625c99603833d100283772127d99a54162233d2cb`
- Alembic head: `0005_remove_migration_index`
- Fresh offline upgrade: 38 `CREATE TABLE` statements including Alembic's version table.
- Explicit offline downgrade chain: 57 table/constraint alteration or drop statements.
- MariaDB target: 10.6+; older versions use the queue's safe conditional-update claim path.
- Live MariaDB migration/seed/locking verification is deferred until the separate VPS/database
  setup session finishes. Offline MariaDB SQL and SQLite metadata/schema checks pass.

## Verification

- Ruff: passed.
- Mypy: 84 source files passed.
- Pytest: 65 passed, including domain, DB schema, repository, provider, queue, worker persistence,
  contract, and full offline vertical-slice coverage.
- OpenAPI executable/committed checksum: passed.
- MAS_B path ownership: passed; no `apps/web/**` or `docs/decisions/mas-a/**` file changed.
- External-network-free vertical slice: passed with mock OAuth, fixtures, three deterministic
  models, score/feed/read/credit/vote/efficacy/share and weight lifecycle.
- MariaDB repository vertical slices: passed on async SQLite for account/privacy, product
  engagement, and admin transaction behavior. Live MariaDB locking/FK enforcement remains an
  environment verification item.

## Provider and database switches

- Offline: `LLM_PROVIDER_MODE=stub` uses three deterministic providers.
- Live: set `LLM_PROVIDER_MODE=live` and all three
  `LLM_{PRIMARY,SECONDARY,TERTIARY}_{ENDPOINT,MODEL_ID,ALIAS,API_KEY}` groups. Startup rejects an
  incomplete configuration. Timeout, bounded retry/backoff, rate limiting, circuit breaking,
  strict schemas, source masking, safe rationale/evidence and redacted metrics are enforced.
- MariaDB/RDBMS login and administrative grants are owned by the concurrent VPS/database setup
  session. This backend pass reads the protected root `.env` as the single source of truth and did
  not overwrite credentials or mutate live grants.

## Queue capacity and limitations

- Concurrency is bounded by `WorkerConfig.max_concurrency`; default is 1 and can be raised after
  representative workload measurement.
- Exactly-once side effects are achieved through unique job dedupe keys plus durable audit-backed
  result idempotency. A dedicated result table is an optional future optimization, not a current
  correctness dependency.
- No throughput number is claimed without a live MariaDB benchmark. Payload/BLOB maximum is
  10 MiB and provider calls remain bounded by their configured rate/timeout controls.

## Security, privacy, legal, and operations follow-ups

- Before production: finish the separate MariaDB/VPS setup, run migrations and the DB/locking
  suite against the chosen server version, and rotate bootstrap credentials.
- Production still requires secret injection, TLS/reverse proxy, firewall/bind policy, backups,
  process supervision and monitoring; these are explicitly outside this local task.
- Complete privacy/copyright/legal review of consent text, retention periods and approved crawler
  sources before public beta. No article body is exposed by the public API.
- Server-wide RDBMS authority is not asserted by this report because grants are being applied and
  verified in the separate infrastructure session.

## Contract requests from MAS_A

- No `docs/decisions/mas-a/CR-*.md` requests were present, so no response file was required.
