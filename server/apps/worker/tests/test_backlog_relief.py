from datetime import UTC, datetime

from db.backlog_relief import next_kst_midnight, source_balanced_cohort


def _row(job_id: str, source_id: str, version_id: str) -> dict[str, str]:
    return {"job_id": job_id, "source_id": source_id, "article_version_id": version_id}


def test_source_balanced_cohort_cycles_sources_before_taking_a_second_article():
    rows = [
        _row("a1", "a", "a-v1"),
        _row("a2", "a", "a-v2"),
        _row("b1", "b", "b-v1"),
        _row("b2", "b", "b-v2"),
        _row("c1", "c", "c-v1"),
    ]

    selected = source_balanced_cohort(rows, 4)

    assert [row["job_id"] for row in selected] == ["a1", "b1", "c1", "a2"]


def test_source_balanced_cohort_deduplicates_versions():
    rows = [_row("a1", "a", "shared"), _row("b1", "b", "shared"), _row("b2", "b", "b-v2")]

    assert [row["job_id"] for row in source_balanced_cohort(rows, 3)] == ["a1", "b2"]


def test_next_kst_midnight_is_the_next_utc_day_boundary():
    now = datetime(2026, 9, 10, 10, 0, tzinfo=UTC)

    assert next_kst_midnight(now) == datetime(2026, 9, 10, 15, 0)
