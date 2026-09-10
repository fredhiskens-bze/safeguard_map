# Safeguard Mechanism Facility Map

An embeddable, self-hosted interactive map of facilities covered by Australia's
Safeguard Mechanism (2020-21 to 2024-25), built for BZE.

## Pipeline

```
data/raw/                      <- yearly Safeguard facility CSVs (source of truth, don't edit)
  |
  v  scripts/build_registry.py
data/processed/facilities_master.csv   <- one row per reconciled real-world facility
data/processed/emissions_long.csv      <- one row per facility-year
  |
  v  scripts/geocode.py (best-effort, low hit rate expected -- no address data in source)
  v  scripts/build_review_workbook.py
docs/facility_coordinates_review.xlsx  <- send to Fred for manual coordinate check/entry
  |
  v  (Fred edits and returns the workbook)
  v  scripts/import_reviewed_workbook.py   <- writes corrections back into facilities_master.csv
  v  scripts/merge_facilities.py           <- one-off manual merges for facilities the
  |                                           fuzzy-matcher split (ownership/rebrand changes)
  v  scripts/build_map_data.py
facilities.json                <- single data file the map app reads (repo root)
  |
  v  index.html + style.css + app.js  (open via serve.py locally, or host anywhere --
                                        e.g. GitHub Pages, since everything the map
                                        needs lives at the repo root)
```

To rebuild everything from scratch after new raw data years are added:

```bash
python scripts/build_registry.py
python scripts/geocode.py
python scripts/build_review_workbook.py
# ... send docs/facility_coordinates_review.xlsx to Fred, wait for it back ...
python scripts/import_reviewed_workbook.py
python scripts/merge_facilities.py   # edit MERGES in the script first, if there are new ones
python scripts/build_map_data.py
```

To preview locally: double-click `serve.py` (or run `python serve.py`) and it opens
http://localhost:8765 in your browser.

## Notes on the data

- **Pre-reform vs reformed mechanism**: 2020-21 to 2022-23 used the original Safeguard
  Mechanism design; 2023-24 onward uses the reformed design (declining baselines, ANZSIC
  sector reporting, SMCs). The two aren't directly comparable — the map's "include
  pre-reform years" toggle and the per-facility chart's "Reform" marker both exist to
  keep this visible rather than implying a continuous like-for-like series.
- **ANZSIC (sector) is only reported from 2023-24 onward.** Facilities are colour-coded
  using their most recently known sector, applied retroactively to earlier years; a
  facility that exited the scheme before 2023-24 has no known sector ("Unclassified").
  Only 4 broad divisions are used (Mining, Manufacturing, Electricity/gas/water/waste,
  Transport) — the data doesn't span any others, and more than ~4 categorical colours
  on a map stop being reliably distinguishable (incl. for colour-blind readers).
- **No address data exists in any source file** — only a state abbreviation. Geocoding
  is a best-effort name search against OpenStreetMap and most facilities will need a
  human to place them correctly; see the confidence column in the review workbook.
- **Facility identity across years is fuzzy-matched**, not exact — names drift between
  years (renames, numbering-prefix changes, ownership changes). Some facilities
  genuinely only appear in 1-2 years (scheme entry/exit); a few edge cases (e.g. two
  differently-owned "designated facilities" sharing one physical site, as happens at
  some joint-venture mines) are intentionally kept as separate rows.
