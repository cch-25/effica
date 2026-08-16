# Development seeds

Apply `001_fake_data.sql` after `alembic upgrade head` against a local MariaDB
database.  It contains only synthetic sources, articles, article versions,
issues, memberships, and deterministic model aliases.  `tier_policy.json` is a
fixture policy document; production policy versions are carried on
`credit_ledger` and `tier_snapshots` rows as specified by the data model.

Do not add accounts, OAuth subjects, tokens, questionnaire responses, private
URLs, or secrets to this directory.
