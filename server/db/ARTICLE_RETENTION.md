# Essential storage and article retention

Schema revision `0017_remove_obsolete_storage` implements this policy in the API,
worker and database maintenance code. Production runs on Vultr; Vercel hosts
the frontend and forwards API requests to the Vultr HTTPS backend.

## Articles

Articles older than seven elapsed days are removed daily at 04:10 Asia/Seoul.
The cutoff uses publication time, falling back to original collection time.
Exactly seven days old is retained until the next scheduled run.

Votes, read sessions and signed-in feed impressions protect their articles.
Share-card article/version references and credit event keys are also protected.
A share card referencing an issue protects its member articles. These exceptions
retain user history without changing credits or deleting accounts.

The site keeps article identifiers, source and URL, publication metadata and
normalized text. Structured assessments and scores support article detail,
comparison and score-history views. Raw crawler payloads and raw model responses
are never persisted. Article history retains the current version and up to two
other versions, plus versions referenced by retained comparisons or share cards.
Comparisons retain the latest reviewed snapshot and latest candidate for each
active issue version. Superseded scores are removed.

Article deletion also removes associated versions, assessments, scores and
issue membership. Comparisons referencing a removed article/version and content
jobs referencing deleted content are discarded. Empty issues are archived.

Minimal URL hashes remain in `article_retention_tombstones`. The crawler skips
old publication dates, and persistence checks these hashes so undated feeds
cannot recreate deleted articles. Tombstones are intentionally retained beyond
seven days; they contain no article body or original URL.

## Operational data

The audit table and raw-storage columns are removed by migration. Source/model
versions live on their records. Worker replay safety
uses `job_receipts` containing a completion marker, with a download pointer for
user exports. Job results no longer duplicate article bodies or AI output.
Completed job inputs are reduced to identifiers needed by site operations.
Admin request receipts preserve retry safety without a separate audit history.

Terminal jobs and their receipts, finished crawl runs and admin request receipts
expire after seven days. Expired login sessions and unused feed impressions are
removed. Stored blobs survive only when referenced by article text, a share card
or an export receipt. Accounts, consent, votes, reading history, credits and
configuration are retained independently of the article cutoff.

Nginx access logging is disabled. Error logs rotate daily or at 5 MB with three
rotations retained. The system journal is capped at 32 MB with three-day retention.
These small diagnostic logs support service operation.

## Operations

- `.ops/run.sh retention backup` streams a complete MariaDB backup into the
  private local sibling `effica-backups` directory and verifies gzip integrity
  and the dump completion marker. It creates no dump on the VPS.
- `.ops/run.sh retention preview` reports article cleanup candidates and
  preservation exceptions without modifying data.
- `.ops/run.sh retention apply` starts full storage maintenance after verifying
  an existing external backup.
- `.ops/run.sh retention status` shows the schedule, latest report and health.
- `.ops/deploy.sh` installs the versioned `server/deploy/` maintenance templates
  during normal deployment. `.env` supplies `VULTR_IPV4_PUBLIC_ADDRESS` and
  `VULTR_PASSWORD`; the deployer targets Vultr directly.

`effica-maintenance.timer` runs `db.storage_maintenance`. Its wrapper first
drains the worker while the API remains available, then stops the API for
cleanup. It restores previously running services on success or failure. A host
lock excludes overlapping maintenance runs. Article deletion uses atomic
batches of 100, rechecks protected references before each batch and additionally
holds a database lock. Failed batches roll back and later runs resume remaining
work. The broader storage cleanup runs in its own transaction.

Backups precede destructive rollout and manual cleanup. The daily timer does
not create external backups. Deployments retain the required runtime modules,
migrations and service templates through `server/deploy.manifest`.
