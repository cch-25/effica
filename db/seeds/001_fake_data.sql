-- Development-only seed.  Every value below is synthetic and safe to replace.
-- No users, OAuth credentials, questionnaire responses, tokens, or secrets are
-- seeded.  The tier policy itself is documented in tier_policy.json because
-- chapter 5 models policy versions on credit/tier snapshots rather than as a
-- separate mutable table.

INSERT INTO sources
    (id, name, source_type, canonical_url, policy_status,
     robots_status, terms_status, active)
VALUES
    ('01J00000000000000000000001', 'Example Public Wire', 'RSS',
     'https://example.invalid/wire', 'APPROVED', 'APPROVED', 'APPROVED', 1),
    ('01J00000000000000000000002', 'Example Policy Desk', 'API',
     'https://example.invalid/policy', 'APPROVED', 'APPROVED', 'APPROVED', 1)
ON DUPLICATE KEY UPDATE id = VALUES(id);

INSERT INTO articles
    (id, source_id, canonical_url, canonical_url_hash, title, author,
     published_at, current_version_id, status)
VALUES
    ('01J00000000000000000000101', '01J00000000000000000000001',
     'https://example.invalid/wire/first-story',
     UNHEX(SHA2('https://example.invalid/wire/first-story', 256)),
     'Example public-policy article', 'Synthetic Desk',
     '2026-01-15 00:00:00.000000', NULL, 'active'),
    ('01J00000000000000000000102', '01J00000000000000000000002',
     'https://example.invalid/policy/second-story',
     UNHEX(SHA2('https://example.invalid/policy/second-story', 256)),
     'Example budget article', 'Synthetic Desk',
     '2026-01-16 00:00:00.000000', NULL, 'active')
ON DUPLICATE KEY UPDATE id = VALUES(id);

INSERT INTO stored_blobs
    (id, sha256, mime_type, byte_size, payload, expires_at, created_at)
VALUES
    ('01J00000000000000000000501',
     UNHEX(SHA2('synthetic article body one', 256)),
     'text/plain; charset=utf-8',
     OCTET_LENGTH('synthetic article body one'),
     'synthetic article body one', NULL, '2026-01-15 00:01:00.000000'),
    ('01J00000000000000000000502',
     UNHEX(SHA2('synthetic article body two', 256)),
     'text/plain; charset=utf-8',
     OCTET_LENGTH('synthetic article body two'),
     'synthetic article body two', NULL, '2026-01-16 00:01:00.000000')
ON DUPLICATE KEY UPDATE id = VALUES(id);

INSERT INTO article_versions
    (id, article_id, content_hash, normalized_text_ref, fetched_at, modified_at)
VALUES
    ('01J00000000000000000000201', '01J00000000000000000000101',
     UNHEX(SHA2('synthetic article body one', 256)),
     '01J00000000000000000000501',
     '2026-01-15 00:01:00.000000', NULL),
    ('01J00000000000000000000202', '01J00000000000000000000102',
     UNHEX(SHA2('synthetic article body two', 256)),
     '01J00000000000000000000502',
     '2026-01-16 00:01:00.000000', NULL)
ON DUPLICATE KEY UPDATE id = VALUES(id);

UPDATE articles
SET current_version_id = CASE id
    WHEN '01J00000000000000000000101' THEN '01J00000000000000000000201'
    WHEN '01J00000000000000000000102' THEN '01J00000000000000000000202'
END
WHERE id IN ('01J00000000000000000000101', '01J00000000000000000000102');

INSERT INTO issues
    (id, title, summary, status, opened_at, last_activity_at, version)
VALUES
    ('01J00000000000000000000301', 'Synthetic public services',
     'Development fixture issue; not a real political claim.', 'active',
     '2026-01-15 00:02:00.000000', '2026-01-16 00:02:00.000000', 1),
    ('01J00000000000000000000302', 'Synthetic fiscal policy',
     'Development fixture issue; not a real political claim.', 'active',
     '2026-01-16 00:02:00.000000', '2026-01-16 00:02:00.000000', 1)
ON DUPLICATE KEY UPDATE id = VALUES(id);

INSERT INTO issue_memberships
    (issue_id, article_id, confidence, created_at)
VALUES
    ('01J00000000000000000000301', '01J00000000000000000000101', 0.9500,
     '2026-01-15 00:03:00.000000'),
    ('01J00000000000000000000302', '01J00000000000000000000102', 0.9500,
     '2026-01-16 00:03:00.000000')
ON DUPLICATE KEY UPDATE issue_id = VALUES(issue_id);

INSERT INTO model_aliases
    (id, alias, provider, actual_model_id, status, config_json)
VALUES
    ('01J00000000000000000000401', 'openai-default', 'openai',
     'gpt-5.6-luna', 'ACTIVE',
     JSON_OBJECT('reasoning_effort', 'xhigh', 'secret_env_name', 'OPENAI_API_KEY'))
ON DUPLICATE KEY UPDATE id = VALUES(id);
