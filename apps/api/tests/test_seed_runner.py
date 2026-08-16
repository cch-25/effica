from db.seeds.seed import _statements


def test_seed_splitter_preserves_semicolons_inside_sql_strings() -> None:
    statements = _statements()

    assert len(statements) == 8
    issue_insert = next(statement for statement in statements if "INSERT INTO issues" in statement)
    assert "Development fixture issue; not a real political claim." in issue_insert
