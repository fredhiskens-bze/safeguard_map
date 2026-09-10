"""
Build facilities.json (repo root) from the reconciled facility registry +
long-format emissions table. This is the single data file the map app loads.

Re-run this any time facilities_master.csv (coordinates) or emissions_long.csv change.
"""
import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
PROCESSED = ROOT / "data" / "processed"

YEAR_ORDER = ["2020-21", "2021-22", "2022-23", "2023-24", "2024-25"]

# ANZSIC subclass code -> broad division, matching the 4 divisions actually
# present in this dataset (see scripts/build_map_data.py comments below).
DIVISION_BY_CODE_PREFIX = {
    "06": "Mining", "07": "Mining", "08": "Mining",
    "11": "Manufacturing", "15": "Manufacturing", "17": "Manufacturing",
    "18": "Manufacturing", "20": "Manufacturing", "21": "Manufacturing",
    "26": "Electricity, gas, water & waste",
    "27": "Electricity, gas, water & waste",
    "28": "Electricity, gas, water & waste",
    "29": "Electricity, gas, water & waste",
    "46": "Transport, postal & warehousing",
    "47": "Transport, postal & warehousing",
    "48": "Transport, postal & warehousing",
    "49": "Transport, postal & warehousing",
    "50": "Transport, postal & warehousing",
}

def anzsic_division(anzsic_str):
    if not isinstance(anzsic_str, str) or not anzsic_str.strip():
        return None
    m = re.search(r"\((\d{3})\)", anzsic_str)
    if not m:
        return None
    code = m.group(1)
    return DIVISION_BY_CODE_PREFIX.get(code[:2], "Other")

def main():
    master = pd.read_csv(PROCESSED / "facilities_master.csv")
    long_df = pd.read_csv(PROCESSED / "emissions_long.csv")

    facilities = []
    skipped_no_coords = 0
    for _, row in master.iterrows():
        fid = row["facility_id"]
        lat, lon = row.get("latitude"), row.get("longitude")
        has_coords = pd.notna(lat) and pd.notna(lon)
        if not has_coords:
            skipped_no_coords += 1

        years = {}
        fac_rows = long_df[long_df["facility_id"] == fid]
        for year, yr_group in fac_rows.groupby("year"):
            # a merged facility can have >1 row in the same year (e.g. an ownership
            # handover mid-year, where old and new owner each reported part of the
            # year's emissions) -- sum the numeric fields, name the combined emitter
            def sum_or_none(col):
                vals = yr_group[col].dropna()
                return None if vals.empty else float(vals.sum())

            emitters = [e for e in yr_group["responsible_emitter"].dropna().unique()]
            years[year] = {
                "mechanism": yr_group["mechanism"].iloc[0],
                "facility_name": yr_group["facility_name"].iloc[0],
                "responsible_emitter": " / ".join(emitters),
                "covered_emissions": sum_or_none("covered_emissions"),
                "baseline": sum_or_none("baseline"),
                "net_emissions": sum_or_none("net_emissions"),
                "mymp_baseline": sum_or_none("mymp_baseline"),
                "mymp_net_emissions": sum_or_none("mymp_net_emissions"),
                "split_year": len(yr_group) > 1,
            }

        anzsic = row.get("anzsic")
        facilities.append({
            "id": fid,
            "name": row["canonical_name"],
            "emitter": row["responsible_emitter"],
            "anzsic": None if pd.isna(anzsic) else anzsic,
            "division": anzsic_division(anzsic) if pd.notna(anzsic) else None,
            "state": row["state"],
            "lat": None if not has_coords else float(lat),
            "lon": None if not has_coords else float(lon),
            "geocode_confidence": row.get("geocode_confidence"),
            "years": years,
        })

    out = {
        "year_order": YEAR_ORDER,
        "legacy_years": ["2020-21", "2021-22", "2022-23"],
        "reformed_years": ["2023-24", "2024-25"],
        "facilities": facilities,
    }
    out_path = ROOT / "facilities.json"
    out_path.write_text(json.dumps(out, indent=None, allow_nan=False))
    print(f"Wrote {out_path}: {len(facilities)} facilities, {skipped_no_coords} without coordinates yet")

if __name__ == "__main__":
    main()
