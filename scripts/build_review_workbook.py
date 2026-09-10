"""
Build the coordinate-review Excel workbook (docs/facility_coordinates_review.xlsx)
from data/processed/facilities_master.csv.
"""
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

ROOT = Path(__file__).parent.parent
PROCESSED = ROOT / "data" / "processed"
DOCS = ROOT / "docs"
DOCS.mkdir(exist_ok=True)

HEADER_FILL = PatternFill("solid", fgColor="1F4E3D")
HEADER_FONT = Font(color="FFFFFF", bold=True)
REVIEW_FILL = PatternFill("solid", fgColor="FFF3CD")
LOW_CONF_FILL = PatternFill("solid", fgColor="FDE2E2")
GOOD_FILL = PatternFill("solid", fgColor="E2F0D9")

def style_header(ws, ncols):
    for col in range(1, ncols + 1):
        cell = ws.cell(row=1, column=col)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    ws.freeze_panes = "A2"
    ws.row_dimensions[1].height = 32

def autosize(ws, df, max_width=45):
    for i, col in enumerate(df.columns, start=1):
        width = min(max(12, df[col].astype(str).str.len().quantile(0.9) + 2), max_width)
        ws.column_dimensions[get_column_letter(i)].width = width

def main():
    master = pd.read_csv(PROCESSED / "facilities_master.csv")

    cols = [
        "facility_id", "canonical_name", "responsible_emitter", "anzsic", "state",
        "years_present", "needs_review", "min_match_confidence",
        "latitude", "longitude", "geocode_confidence", "geocode_matched_place",
        "name_2020-21", "name_2021-22", "name_2022-23", "name_2023-24", "name_2024-25",
    ]
    df = master[[c for c in cols if c in master.columns]].copy()
    df = df.rename(columns={
        "facility_id": "ID",
        "canonical_name": "Facility name (canonical)",
        "responsible_emitter": "Responsible emitter (latest)",
        "anzsic": "ANZSIC (sector)",
        "state": "State(s)",
        "years_present": "Years in scheme",
        "needs_review": "Name-match flagged for review",
        "min_match_confidence": "Name-match confidence score",
        "latitude": "Latitude",
        "longitude": "Longitude",
        "geocode_confidence": "Geocode confidence",
        "geocode_matched_place": "Geocode matched place (for reference)",
        "name_2020-21": "Name in 2020-21",
        "name_2021-22": "Name in 2021-22",
        "name_2022-23": "Name in 2022-23",
        "name_2023-24": "Name in 2023-24",
        "name_2024-25": "Name in 2024-25",
    })
    df = df.sort_values(["Name-match flagged for review", "Geocode confidence"], ascending=[False, True])

    wb = Workbook()

    # --- Instructions sheet ---
    ws0 = wb.active
    ws0.title = "Instructions"
    instructions = [
        ["Safeguard Mechanism facility map -- coordinate review workbook"],
        [""],
        ["What this is:"],
        ["One row per real-world facility, reconciled across the 2020-21 to 2024-25 Safeguard Mechanism data years."],
        ["Facility names sometimes changed between years -- the 'Name in <year>' columns show what each facility was called each year, so you can sanity-check the automatic matching."],
        [""],
        ["What to do:"],
        ["1. Go to the 'Facilities' tab."],
        ["2. Rows are sorted with the ones needing attention first: flagged name-matches, then low/no-confidence geocoding."],
        ["3. Check 'Latitude'/'Longitude' for each row. These were auto-filled by searching the facility name against OpenStreetMap where possible -- there is no address data in the source files, only a state, so many are approximate, wrong, or blank."],
        ["4. Correct or fill in Latitude/Longitude directly (decimal degrees, e.g. -33.8688, 151.2093). Leave blank if you can't place it -- it just won't appear on the map."],
        ["5. If 'Name-match flagged for review' is TRUE, check the per-year name columns: is this really one facility that was renamed, or actually two different facilities that got merged? Split or fix in the 'Facilities' tab if needed (see 'Facility name (canonical)' cell)."],
        [""],
        ["Geocode confidence key:"],
        ["  likely   -- matched a specific place/site feature in the right state"],
        ["  possible -- matched something in the right state, but a generic location (e.g. a suburb centroid), not necessarily the exact site"],
        ["  low      -- match found but state didn't line up, or the match looks generic -- treat as a rough starting point only"],
        ["  not found -- no coordinates could be found automatically, needs manual entry"],
        [""],
        ["When you're done, send the file back and the map will be built from these coordinates."],
    ]
    for r in instructions:
        ws0.append(r)
    ws0["A1"].font = Font(bold=True, size=14)
    ws0.column_dimensions["A"].width = 110
    for row in ws0.iter_rows():
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")

    # --- Facilities sheet ---
    ws1 = wb.create_sheet("Facilities")
    ws1.append(list(df.columns))
    for row in df.itertuples(index=False):
        ws1.append(list(row))
    style_header(ws1, len(df.columns))
    autosize(ws1, df)

    review_col = list(df.columns).index("Name-match flagged for review") + 1
    conf_col = list(df.columns).index("Geocode confidence") + 1
    for r in range(2, ws1.max_row + 1):
        if str(ws1.cell(r, review_col).value).strip().lower() == "true":
            ws1.cell(r, review_col).fill = REVIEW_FILL
        conf_val = str(ws1.cell(r, conf_col).value).strip().lower()
        if conf_val in ("low", "not found", "none"):
            ws1.cell(r, conf_col).fill = LOW_CONF_FILL
        elif conf_val == "likely":
            ws1.cell(r, conf_col).fill = GOOD_FILL

    ws1.auto_filter.ref = ws1.dimensions

    wb.save(DOCS / "facility_coordinates_review.xlsx")
    print(f"Wrote {DOCS / 'facility_coordinates_review.xlsx'} ({len(df)} facilities)")

if __name__ == "__main__":
    main()
