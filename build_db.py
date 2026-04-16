"""Load every data/*.tsv into DuckDB and emit an interned JSON payload.

Produces:
    nsf_grfp.duckdb   -- DuckDB database with an `awardees` table covering all years
    awardees.json     -- string-interned JSON payload consumed by the web UI

Run with:
    uv run --with duckdb --with loguru python build_db.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import duckdb
from loguru import logger

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
DB_PATH = ROOT / "nsf_grfp.duckdb"
JSON_PATH = ROOT / "awardees.json"

TSV_PATTERN = re.compile(r"^(awards|honorable_mentions)_(\d{4})\.tsv$")


def split_field(field: str) -> tuple[str, str]:
    """Split a "Broad - Specific" field label; return broad-only when no dash."""
    if " - " in field:
        broad, specific = field.split(" - ", 1)
        return broad.strip(), specific.strip()
    return field.strip(), ""


def intern(values) -> tuple[list[str], dict[str, int]]:
    """Assign a stable index to each distinct string in insertion order."""
    seen: dict[str, int] = {}
    ordered: list[str] = []
    for v in values:
        if v not in seen:
            seen[v] = len(ordered)
            ordered.append(v)
    return ordered, seen


def load_tsv(con: duckdb.DuckDBPyConnection, tsv: Path, award_type: str, year: int) -> int:
    con.execute("""
        CREATE TEMP TABLE stage AS
        SELECT * FROM read_csv_auto(?, delim='\t', header=true, all_varchar=true)
    """, [str(tsv)])
    rows = con.execute("SELECT * FROM stage").fetchall()
    con.execute("DROP TABLE stage")

    records = []
    for row in rows:
        name, bacc, field, current = (list(row) + [None, None, None, None])[:4]
        broad, specific = split_field(field or "")
        records.append((
            (name or "").strip(),
            (bacc or "").strip(),
            broad,
            specific,
            (field or "").strip(),
            (current or "").strip(),
            award_type,
            year,
        ))
    if records:
        con.executemany(
            "INSERT INTO awardees VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            records,
        )
    return len(records)


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

    tsvs = sorted(DATA_DIR.glob("*.tsv"))
    logger.info("found {} TSV files in {}", len(tsvs), DATA_DIR)

    for tsv in tsvs:
        m = TSV_PATTERN.match(tsv.name)
        if not m:
            logger.warning("unexpected filename, skipping: {}", tsv.name)
            continue
        kind, year_str = m.groups()
        year = int(year_str)
        award_type = "Award" if kind == "awards" else "Honorable Mention"
        n = load_tsv(con, tsv, award_type, year)
        logger.info("{}: {} rows", tsv.name, n)

    total = con.execute("SELECT COUNT(*) FROM awardees").fetchone()[0]
    year_span = con.execute(
        "SELECT MIN(award_year), MAX(award_year) FROM awardees"
    ).fetchone()
    logger.info("total rows: {} ({} through {})", total, *year_span)
    by_type = con.execute(
        "SELECT award_type, COUNT(*) FROM awardees GROUP BY award_type ORDER BY award_type"
    ).fetchall()
    for t, c in by_type:
        logger.info("  {}: {}", t, c)

    con.execute("CREATE INDEX idx_name ON awardees(name)")
    con.execute("CREATE INDEX idx_inst ON awardees(current_inst)")
    con.execute("CREATE INDEX idx_year ON awardees(award_year)")

    payload = con.execute("""
        SELECT name, baccalaureate, field_broad, field_specific, current_inst, award_type, award_year
        FROM awardees
        ORDER BY award_year DESC, name
    """).fetchall()

    # Pool baccalaureate and current institutions into a single lookup so the
    # table only lists each school once even when students stay at the same
    # place.
    inst_pool = [r[1] or "" for r in payload] + [r[4] or "" for r in payload]
    inst_list, inst_ix = intern(inst_pool)
    fb_list, fb_ix = intern([r[2] or "" for r in payload])
    fs_list, fs_ix = intern([r[3] or "" for r in payload])

    years_list = sorted({r[6] for r in payload}, reverse=True)
    years_ix = {y: i for i, y in enumerate(years_list)}

    rows_out = [
        [
            name,
            inst_ix[bacc or ""],
            fb_ix[fb or ""],
            fs_ix[fs or ""],
            inst_ix[current or ""],
            years_ix[year],
            "A" if award_type == "Award" else "H",
        ]
        for name, bacc, fb, fs, current, award_type, year in payload
    ]

    out = {
        "inst": inst_list,
        "fb": fb_list,
        "fs": fs_list,
        "years": years_list,
        "rows": rows_out,
    }
    JSON_PATH.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    logger.info(
        "wrote {} — rows={} inst={} fb={} fs={} years={} ({} KB)",
        JSON_PATH.name, len(rows_out), len(inst_list), len(fb_list), len(fs_list),
        len(years_list), JSON_PATH.stat().st_size // 1024,
    )

    con.close()


if __name__ == "__main__":
    main()
