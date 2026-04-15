"""Load scraped NSF GRFP 2026 TSV files into DuckDB and emit JSON for the web UI.

Produces:
    nsf_grfp_2026.duckdb   -- a DuckDB database with table `awardees`
    awardees.json          -- compact JSON embedded in the static site

Run with:
    uv run --with duckdb build_db.py
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
from loguru import logger

ROOT = Path(__file__).parent
DB_PATH = ROOT / "nsf_grfp_2026.duckdb"
JSON_PATH = ROOT / "awardees.json"
AWARDS_TSV = ROOT / "awards_2026.tsv"
HM_TSV = ROOT / "honorable_mentions_2026.tsv"


def split_field(field: str) -> tuple[str, str]:
    """Split a "Broad - Specific" field string into its two parts."""
    if " - " in field:
        broad, specific = field.split(" - ", 1)
        return broad.strip(), specific.strip()
    return field.strip(), ""


def main() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()

    con = duckdb.connect(str(DB_PATH))
    con.execute("""
        CREATE TABLE awardees (
            name              TEXT NOT NULL,
            baccalaureate     TEXT,
            field_broad       TEXT,
            field_specific    TEXT,
            field_full        TEXT,
            current_inst      TEXT,
            award_type        TEXT NOT NULL,
            award_year        INTEGER NOT NULL
        )
    """)

    for tsv_path, award_type in [(AWARDS_TSV, "Award"), (HM_TSV, "Honorable Mention")]:
        staging = f"stage_{award_type.replace(' ', '_').lower()}"
        con.execute(f"""
            CREATE TEMP TABLE {staging} AS
            SELECT * FROM read_csv_auto(?, delim='\t', header=true, all_varchar=true)
        """, [str(tsv_path)])
        rows = con.execute(f"SELECT * FROM {staging}").fetchall()
        logger.info("Loaded {} rows from {}", len(rows), tsv_path.name)

        records = []
        for name, bacc, field, current in rows:
            broad, specific = split_field(field or "")
            records.append((
                (name or "").strip(),
                (bacc or "").strip(),
                broad,
                specific,
                (field or "").strip(),
                (current or "").strip(),
                award_type,
                2026,
            ))
        con.executemany(
            "INSERT INTO awardees VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            records,
        )

    total = con.execute("SELECT COUNT(*) FROM awardees").fetchone()[0]
    by_type = con.execute(
        "SELECT award_type, COUNT(*) FROM awardees GROUP BY award_type ORDER BY award_type"
    ).fetchall()
    logger.info("Total rows in DB: {}", total)
    for t, c in by_type:
        logger.info("  {}: {}", t, c)

    con.execute("CREATE INDEX idx_name ON awardees(name)")
    con.execute("CREATE INDEX idx_inst ON awardees(current_inst)")

    payload = con.execute("""
        SELECT name, baccalaureate, field_broad, field_specific, current_inst, award_type
        FROM awardees
        ORDER BY name
    """).fetchall()

    compact = [
        {
            "n": name,
            "b": bacc,
            "fb": fb,
            "fs": fs,
            "c": current,
            "t": "A" if award_type == "Award" else "H",
        }
        for name, bacc, fb, fs, current, award_type in payload
    ]
    JSON_PATH.write_text(json.dumps(compact, ensure_ascii=False, separators=(",", ":")))
    logger.info("Wrote {} ({} records)", JSON_PATH.name, len(compact))

    con.close()


if __name__ == "__main__":
    main()
