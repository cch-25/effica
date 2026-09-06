"""Reject the legacy unmetered file-based paid analysis path.

Live analysis belongs to the durable worker queue, which shares its input
cache, daily article cohort, and cost ledger across all worker processes.
Existing snapshot assessments remain usable by the normal seed importer.
"""

from __future__ import annotations

import argparse


def analyze_all(*, workers: int, force: bool) -> int:
    del workers, force
    raise RuntimeError(
        "직접 LLM 분석은 비활성화되었습니다. DB 적재 후 중복 차단과 "
        "일일 예산을 공유하는 worker analyze 작업을 사용하세요."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Legacy direct LLM analysis is disabled")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    return analyze_all(workers=args.workers, force=args.force)


if __name__ == "__main__":
    raise SystemExit(main())
