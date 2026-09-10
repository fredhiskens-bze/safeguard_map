"""
Import Fred's edits from docs/facility_coordinates_review.xlsx back into
data/processed/facilities_master.csv, matched by the stable facility ID
(so renaming the 'Facility name (canonical)' cell in the workbook is safe).

Run this after the workbook comes back, then re-run build_map_data.py.
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
PROCESSED = ROOT / "data" / "processed"
DOCS = ROOT / "docs"

def main():
    wb_path = DOCS / "facility_coordinates_review.xlsx"
    sheet = pd.read_excel(wb_path, sheet_name="Facilities")
    master = pd.read_csv(PROCESSED / "facilities_master.csv")

    sheet = sheet.set_index("ID")
    master = master.set_index("facility_id")

    updated_coords = 0
    updated_names = 0
    updated_anzsic = 0
    for fid, row in sheet.iterrows():
        if fid not in master.index:
            print(f"  ! {fid} in workbook but not in master registry, skipping")
            continue
        lat, lon = row.get("Latitude"), row.get("Longitude")
        if pd.notna(lat) and pd.notna(lon):
            if (master.at[fid, "latitude"] != lat) or (master.at[fid, "longitude"] != lon):
                updated_coords += 1
            master.at[fid, "latitude"] = lat
            master.at[fid, "longitude"] = lon

        new_name = row.get("Facility name (canonical)")
        if pd.notna(new_name) and new_name != master.at[fid, "canonical_name"]:
            master.at[fid, "canonical_name"] = new_name
            updated_names += 1

        new_anzsic = row.get("ANZSIC (sector)")
        if pd.notna(new_anzsic) and new_anzsic != master.at[fid, "anzsic"]:
            master.at[fid, "anzsic"] = new_anzsic
            updated_anzsic += 1

    master = master.reset_index().rename(columns={"index": "facility_id"})
    master.to_csv(PROCESSED / "facilities_master.csv", index=False)
    print(f"Updated {updated_coords} coordinate pairs, {updated_names} canonical names, {updated_anzsic} ANZSIC sectors.")
    print("Now re-run: python scripts/build_map_data.py")

if __name__ == "__main__":
    main()
