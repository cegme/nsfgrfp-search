# NSF GRFP 2026 Awardee Search

A scrape of the 2026 NSF Graduate Research Fellowship Program awardees and honorable mentions, a DuckDB database over them, and a single-page website with keyword search.

## Contents

| File | What it is |
|------|------------|
| `awards_2026.tsv` | Raw awarded recipients scraped from research.gov (2,599 rows, UTF-8, tab-separated) |
| `honorable_mentions_2026.tsv` | Raw honorable mentions scraped from research.gov (1,440 rows, UTF-8, tab-separated) |
| `build_db.py` | Loads both TSV files into DuckDB and emits `awardees.json` |
| `nsf_grfp_2026.duckdb` | DuckDB database with one `awardees` table |
| `awardees.json` | Compact JSON payload consumed by the web UI |
| `index.html` | Single-page search UI (no build step, no framework) |

Data snapshot date: 2026-04-14.
Source: <https://www.research.gov/grfp/AwardeeList.do?method=loadAwardeeList>

## Data schema

The `awardees` table in `nsf_grfp_2026.duckdb`:

| Column | Type | Notes |
|--------|------|-------|
| `name` | TEXT | `Last, First M` |
| `baccalaureate` | TEXT | Undergraduate institution |
| `field_broad` | TEXT | First half of the field label (e.g. `Engineering`, `Life Sciences`) |
| `field_specific` | TEXT | Second half (e.g. `Civil Engineering`) |
| `field_full` | TEXT | Original unsplit field label |
| `current_inst` | TEXT | Institution at time of application |
| `award_type` | TEXT | `Award` or `Honorable Mention` |
| `award_year` | INTEGER | Always `2026` in this snapshot |

## Clone

```sh
gh repo clone cegme/nsfgrfp-search
# or
git clone https://github.com/cegme/nsfgrfp-search.git
cd nsfgrfp-search
```

The repo is self-contained: the raw TSV files, the DuckDB database, the JSON payload, and the web UI are all checked in, so the site works immediately with no build step.

## Run locally

### View the search site

```sh
uv run python -m http.server 8765
```

Then open <http://127.0.0.1:8765>.

### Rebuild the DuckDB database and JSON payload

```sh
uv run --with duckdb --with loguru python build_db.py
```

This regenerates `nsf_grfp_2026.duckdb` and `awardees.json` from the two TSV files.

### Query the database directly

```sh
uv run --with duckdb python -c "
import duckdb
con = duckdb.connect('nsf_grfp_2026.duckdb', read_only=True)
rows = con.execute('''
    SELECT name, current_inst, field_specific
    FROM awardees
    WHERE award_type = 'Award' AND current_inst ILIKE '%MIT%'
    ORDER BY name
''').fetchall()
for r in rows:
    print(r)
"
```

Or open an interactive shell with `duckdb nsf_grfp_2026.duckdb`.

## How the scrape worked

The research.gov awardee list supports an undocumented TSV export.
The workflow is a two-step session:

1. POST the search form to seed the session with a year plus award type.
2. GET the export URL, which returns a tab-separated file (mislabeled as `.xls`).

```sh
# Offered awards for 2026
curl -s -c cookies.txt "https://www.research.gov/grfp/AwardeeList.do?method=loadAwardeeList" -o /dev/null
curl -s -b cookies.txt -c cookies.txt -X POST "https://www.research.gov/grfp/AwardeeList.do" \
  --data "method=loadAwardeeList&awardYear=2026&awardType=A&action=Search" -o /dev/null
curl -s -b cookies.txt "https://www.research.gov/grfp/AwardeeList.do?method=sort&exportType=2" \
  | iconv -f ISO-8859-1 -t UTF-8 > awards_2026.tsv
```

Swap `awardType=A` for `awardType=H` to pull honorable mentions.
The response is ISO-8859-1 even though the server labels it `application/vnd.ms-excel`, so it needs to be transcoded before DuckDB will read it.

## Site features

- Multi-token substring search across name, both institutions, and field.
- Filter by award type (awarded / honorable mention) and broad field.
- Sortable columns; click a header to toggle direction.
- Match highlighting on each keyword.
- Paginated at 50 rows per page.
- All filtering runs client-side over a 593 KB JSON payload. No network after initial load.

## Re-scrape a fresh year

If you want to pull a different year or refresh the snapshot, run the two `curl` calls above (swap `awardYear=2026` for the year you want, and run once for `awardType=A` and once for `awardType=H`), transcode to UTF-8, then regenerate the database and JSON:

```sh
uv run --with duckdb --with loguru python build_db.py
```

## Repository

Private repo: <https://github.com/cegme/nsfgrfp-search>

## Disclaimer

This page is unaffiliated with NSF. The authoritative list lives at research.gov.
