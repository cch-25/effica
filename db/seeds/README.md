# Development seeds

Run `python -m db.seeds.seed` after `alembic upgrade head` against a local
MariaDB database.  The runner applies `001_fake_data.sql` and
`002_demo_articles.sql` in order.  The second fixture adds exactly 100
synthetic articles (102 total with the baseline), each with a stored blob,
article version, model assessment, active score, and current-version pointer.
The 100 rows are spread over four synthetic sources and ten synthetic issues
so feed and issue screens have useful variety.  Re-running the runner is
idempotent.

The fixtures contain only synthetic sources, articles, article versions, blobs,
scores, assessments, issues, memberships, and deterministic model aliases.
`tier_policy.json` is a fixture policy document; production policy versions are
carried on `credit_ledger` and `tier_snapshots` rows as specified by the data
model.

Do not add accounts, OAuth subjects, tokens, questionnaire responses, private
URLs, or secrets to this directory.
