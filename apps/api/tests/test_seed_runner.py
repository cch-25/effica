from db.seeds.seed import _statements


def test_seed_splitter_preserves_semicolons_inside_sql_strings() -> None:
    statements = _statements()

    assert len(statements) == 18
    issue_insert = next(statement for statement in statements if "INSERT INTO issues" in statement)
    assert "Development fixture issue; not a real political claim." in issue_insert


def test_demo_seed_contains_exactly_one_hundred_articles_and_scores() -> None:
    statements = _statements()
    demo_articles = next(
        statement
        for statement in statements
        if "INSERT INTO articles" in statement and "demo/article-" in statement
    )
    demo_versions = next(
        statement
        for statement in statements
        if "INSERT INTO article_versions" in statement and "demo report" in statement
    )
    demo_scores = next(
        statement
        for statement in statements
        if "INSERT INTO score_versions" in statement and "assessment_id" in statement
    )
    demo_memberships = next(
        statement
        for statement in statements
        if "INSERT INTO issue_memberships" in statement
        and "01J00000000000000000001001" in statement
    )

    assert demo_articles.count("UNHEX(SHA2") == 100
    assert demo_versions.count("Synthetic demo report") == 100
    assert demo_scores.count("assessment_id") == 100
    for article_offset in range(10):
        issue_id = f"01J00000000000000000000{303 + article_offset:03d}"
        article_id = f"01J000000000000000000{1001 + article_offset:05d}"
        assert f"'{issue_id}', '{article_id}'" in demo_memberships
