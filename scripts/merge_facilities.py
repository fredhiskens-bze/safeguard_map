"""
Manually merge two reconciled facility rows that the automatic fuzzy-matcher
kept separate (e.g. an ownership handover where the facility name stayed
the same or changed, but the responsible emitter changed enough to pull the
combined match score below the auto-accept threshold).

Edit MERGES below and run. `keep` survives with its facility_id; `drop`'s
years get folded into it, then its row is removed.

If both facilities reported for the *same* year (a mid-year ownership
transition, e.g. old owner + new owner each reporting part of the year),
that year will have two emissions_long rows under one facility_id --
build_map_data.py sums them, which is what you want.
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
PROCESSED = ROOT / "data" / "processed"

# (keep_id, drop_id, optional canonical name override)
# Batch 1 (2026-09-09, Fred-identified): Pyrenees, Blackwater, Chandala, Curtis Island GLNG -- already applied.
# Batch 2 (2026-09-09, proactive scan for the same ownership/rebrand-name-collision pattern,
# confirmed high-confidence by Fred):
MERGES = [
    ("F0052", "F0234", "Daunia Coal Mine"),        # Whitehaven (was BMA) -- same BHP asset sale as Blackwater
    ("F0157", "F0279", "Poitrel Mine"),            # Stanmore Resources (was BHP Mitsui Coal)
    ("F0191", "F0278", "South Walker Creek"),      # Stanmore Resources (was BHP Mitsui Coal)
    ("F0198", "F0199", "Telfer Gold Mine"),        # Greatland Holdings (was Newcrest/Newmont)
    ("F0246", "F0118", "Moranbah"),                # Dyno Nobel (was Incitec Pivot) -- explosives rebrand
    ("F0236", "F0069", "Gibson Island"),           # Dyno Nobel (was Incitec Pivot)
    ("F0250", "F0152", "Phosphate Hill"),          # Dyno Nobel (was Incitec Pivot)
    ("F0248", "F0137", "Norske Skog Boyer Mill"),  # Boyer Paper Mill Ltd (was Norske Skog)
    ("F0251", "F0154", "Pilgangoora Operations"),  # PLS Group Ltd (was Pilbara Minerals)
    ("F0247", "F0261", "Mt Marion Lithium Project"),  # Mt Marion Lithium Pty Ltd (was Reed Industrial Minerals)
    ("F0077", "F0275", "Grosvenor Mine"),          # same-year dual Anglo Coal entity report, like Blackwater
]

# Batch 3 (2026-09-09, Fred-identified from his own site knowledge):
MERGES += [
    # "New Illawarra Road Landfill" is the site now branded Cleanaway Lucas Heights
    # Resource Recovery Park -- three years of the same site under a chain of
    # operators (SUEZ -> Veolia [Veolia's 2022 global acquisition of SUEZ] -> Cleanaway),
    # with 2021-22 a dual-entity handover year like Blackwater/Telfer/Grosvenor.
    ("F0229", "F0269", "Cleanaway Lucas Heights Resource Recovery Park"),
    ("F0229", "F0270", "Cleanaway Lucas Heights Resource Recovery Park"),
    ("F0060", "F0258", "Ensham Coal Mine"),  # Ensham Resources Minesite -- same mine, renamed
]

# Batch 4 (2026-09-09, Fred-identified):
MERGES += [
    ("F0084", "F0277", "InfraBuild Steel - Laverton Steel Mill"),  # was Liberty OneSteel (GFG Alliance rebrand)
    ("F0037", "F0262", "Centurion Coal Mine"),   # was North Goonyella Coal Mine / Peabody -- sold & renamed after 2018 mine fire
    ("F0140", "F0281", "Nyrstar Port Pirie Facility"),  # was Nyrstar Port Pirie Smelter
    ("F0103", "F0282", "Liberty Bell Bay"),      # was TEM01 / Tasmanian Electro Metallurgical Co (TEMCO) --
                                                   # NOT the same as "Bell Bay Smelter" (F0018, Rio Tinto Aluminium),
                                                   # a separate facility in the same industrial precinct
]

YEAR_ORDER = ["2020-21", "2021-22", "2022-23", "2023-24", "2024-25"]

def main():
    master = pd.read_csv(PROCESSED / "facilities_master.csv").set_index("facility_id")
    long_df = pd.read_csv(PROCESSED / "emissions_long.csv")

    for keep, drop, name_override in MERGES:
        if keep not in master.index or drop not in master.index:
            print(f"  ! skipping ({keep}, {drop}) -- one of these isn't in the master registry (already merged?)")
            continue

        k, d = master.loc[keep], master.loc[drop]

        years_present = sorted(set(k["years_present"].split(",")) | set(d["years_present"].split(",")),
                                key=YEAR_ORDER.index)
        master.at[keep, "years_present"] = ",".join(years_present)
        master.at[keep, "n_years"] = len(years_present)
        master.at[keep, "state"] = "/".join(sorted(set(str(k["state"]).split("/")) | set(str(d["state"]).split("/"))))
        if pd.isna(k["anzsic"]) and pd.notna(d["anzsic"]):
            master.at[keep, "anzsic"] = d["anzsic"]
        if pd.isna(k["latitude"]) and pd.notna(d["latitude"]):
            master.at[keep, "latitude"] = d["latitude"]
            master.at[keep, "longitude"] = d["longitude"]
        for y in YEAR_ORDER:
            col = f"name_{y}"
            if pd.isna(master.at[keep, col]) and pd.notna(d.get(col)):
                master.at[keep, col] = d[col]
        if name_override:
            master.at[keep, "canonical_name"] = name_override
        master.at[keep, "needs_review"] = False
        master.at[keep, "min_match_confidence"] = 100  # manually confirmed by Fred

        long_df.loc[long_df["facility_id"] == drop, "facility_id"] = keep
        master = master.drop(index=drop)
        print(f"Merged {drop} into {keep} ({name_override or k['canonical_name']})")

    master.reset_index().to_csv(PROCESSED / "facilities_master.csv", index=False)
    long_df.to_csv(PROCESSED / "emissions_long.csv", index=False)
    print(f"\n{len(master)} facilities remain after merging.")

if __name__ == "__main__":
    main()
