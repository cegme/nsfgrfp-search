# /// script
# dependencies = ["requests", "loguru"]
# ///
"""Scrape NSF GRFP awardees and honorable mentions for every available year.

Each (year, award_type) request needs its own POST/GET sequence because the
export URL reads state from the server-side session. Older years have no
honorable-mention data on file; those responses come back as HTML and are
detected and skipped.

Run:
    uv run scrape_all_years.py
"""

from __future__ import annotations

import re
import time
from pathlib import Path

import requests
from loguru import logger

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"

INDEX_URL = "https://www.research.gov/grfp/AwardeeList.do?method=loadAwardeeList"
POST_URL = "https://www.research.gov/grfp/AwardeeList.do"
EXPORT_URL = "https://www.research.gov/grfp/AwardeeList.do?method=sort&exportType=2"
HEADERS = {
    "User-Agent": "nsfgrfp-search/1.0 (github.com/cegme/nsfgrfp-search)",
    "Accept": "*/*",
}
REQUEST_DELAY = 0.5


def list_years(html: str) -> list[int]:
    years = {int(m) for m in re.findall(r'<option\s+value="(\d{4})"', html)}
    return sorted(years)


def fetch_tsv(session: requests.Session, year: int, award_type: str) -> bytes | None:
    """Run the POST+GET export sequence for one (year, award_type).

    Returns UTF-8 encoded TSV bytes, or None if the server responded with an
    HTML error page (typical for years with no data of that type).
    """
    session.cookies.clear()
    session.get(INDEX_URL, headers=HEADERS, timeout=30)
    session.post(
        POST_URL,
        data={
            "method": "loadAwardeeList",
            "awardYear": str(year),
            "awardType": award_type,
            "action": "Search",
        },
        headers=HEADERS,
        timeout=30,
    )
    response = session.get(EXPORT_URL, headers=HEADERS, timeout=60)
    raw = response.content
    head = raw[:128].lstrip().lower()
    if head.startswith(b"<") or b"<html" in head:
        return None
    return raw.decode("iso-8859-1").encode("utf-8")


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    session = requests.Session()

    index_html = session.get(INDEX_URL, headers=HEADERS, timeout=30).text
    years = list_years(index_html)
    logger.info("years: {} through {} (n={})", years[0], years[-1], len(years))

    attempts = 0
    wrote = 0
    skipped_existing = 0
    skipped_empty = 0

    for year in years:
        for award_type, label in [("A", "awards"), ("H", "honorable_mentions")]:
            out = DATA_DIR / f"{label}_{year}.tsv"
            if out.exists() and out.stat().st_size > 200:
                skipped_existing += 1
                continue

            attempts += 1
            for attempt in range(3):
                try:
                    body = fetch_tsv(session, year, award_type)
                    break
                except requests.RequestException as exc:
                    logger.warning(
                        "retry {} {} attempt {}: {}",
                        year, label, attempt + 1, exc,
                    )
                    time.sleep(1 + attempt * 2)
            else:
                logger.error("giving up on {} {}", year, label)
                continue

            if body is None:
                logger.info("skip {} {} (no data)", year, label)
                skipped_empty += 1
                time.sleep(REQUEST_DELAY)
                continue

            out.write_bytes(body)
            line_count = body.count(b"\n")
            logger.info("wrote {} ({} lines)", out.name, line_count)
            wrote += 1
            time.sleep(REQUEST_DELAY)

    logger.info(
        "done. wrote={} existing={} empty={} attempts={}",
        wrote, skipped_existing, skipped_empty, attempts,
    )


if __name__ == "__main__":
    main()
