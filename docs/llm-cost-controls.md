# LLM essential-use policy

## Confirmed incident, 2026-09-06 KST

The retained production database contained 1,670 successful assessment rows
for 507 distinct articles that day. Eight MSS page IDs each had 62 assessed
versions. Twelve sampled adjacent-version pairs from six MSS/FSC page IDs
differed only in numeric text near view-count labels.

In the retained three-day window, 2,717 comparison jobs belonged to 25 repeated
input groups. The largest group had 249 jobs for the same three article
versions and prompt, with 249 issue versions. Job attempts and assessment rows
are not independently verified API request counts or billed dollars.

The extraction parser included boilerplate descendants and did not apply its
own boilerplate flag when saving blocks. Repeated clustering also incremented
issue versions without substantive input changes, invalidating job dedupe.

## Runtime policy

- Actual article-body containers take priority over page-level content.
  View counters, related items and comments are excluded structurally.
  Index pages without article evidence are not analyzed. No topic blacklist
  is used to substitute for duplicate prevention.
- An unchanged title and body retain their current article version.
  A changed title is versioned as well as a changed body. Legacy unchanged
  versions are not invalidated solely by deployment.
- Unchanged issue clustering neither increments the issue version nor refreshes
  activity time. Comparison job identity excludes the issue version.
- Exact paid input keys cover the effective prompt, schema and model settings.
  Responses are durably saved before downstream result application. Identical
  input reuses its response even across jobs, restarts or date rollover.
- A possibly billed submission without a saved response is never automatically
  resubmitted. A timeout may therefore leave that input unassessed. This is an
  intentional cost-first policy, not an exactly-once delivery guarantee.
- Single-article analysis and comparisons share one KST daily cohort of at most
  100 distinct article IDs. Cached results do not use a paid-transmission slot.
  An article has at most one new single-article submission per KST day.
- The additional ceiling is 10 changed, active-event comparisons and 110 total
  submitted-request authorizations per day. The union of article IDs stays at
  100, not 100 plus the comparison members.
- Live calls use GPT-5.6 Luna, reasoning `none`, no provider-local retries,
  bounded input and output lengths, and a durable conservative $5 daily cost
  reservation ceiling. Non-budgeted models fail closed.
- Overflow work is marked SKIPPED rather than building an ever-growing paid
  backlog. The next day permits new eligible inputs; it does not automatically
  replay every skipped job. A limit of 100 is a maximum, not a promise of 100
  completed analyses.
- Crawling, deterministic clustering and scoring do not require LLM calls.
  Crawling may discover more than 100 pages. The 100-article limit applies to
  actual new paid analysis/comparison input, not HTTP discovery.
- The legacy direct file-based paid analysis command is disabled. All live
  application analysis runs through the shared worker guard.

## Accounting and diagnosis

`llm_requests` retains globally unique input keys and validated response data.
`llm_daily_articles` records the shared article cohort. `llm_daily_usage` records
conservative authorizations, not invoices. These tables must not be cleared by
routine article or job retention, because clearing them would permit rebilling.

The $5 ceiling protects this application's controlled calls with the supported
model pricing. It cannot govern unrelated applications using the same API key
or replace provider billing reports. Pricing changes require updating the
conservative estimator before enabling a different paid model.

On 2026-09-06, the daily ledger was deliberately seeded at its limit as an
emergency stop. That day's ledger total must not be reported as measured spend.

Run `.ops/run.sh llm-audit` for SELECT-only diagnostics, keeping reports in
`output/`. Run `.ops/run.sh test` for offline regressions. The isolated MariaDB
test is `RUN_MARIADB_INTEGRATION=1 .ops/run.sh integration
tests/integration/test_llm_request_ledger_mariadb.py`; it creates and removes only
its own randomly named test tables and makes no paid provider requests.
