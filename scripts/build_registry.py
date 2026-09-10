"""
Reconcile Safeguard Mechanism facility data across multiple financial years
into one master facility registry + a long-format emissions table.

Handles:
- schema differences between the pre-reform (2020-21 to 2022-23) and
  reformed (2023-24, 2024-25) Safeguard Mechanism data formats
- facility name drift between years (fuzzy matched, confidence-scored)
- numbers formatted with commas / stray whitespace / 'n/a' / '-' placeholders

Outputs (data/processed/):
- facilities_master.csv   one row per reconciled real-world facility
- emissions_long.csv      one row per facility-year (covered emissions, baseline, etc.)
"""
import re
import pandas as pd
from pathlib import Path
from rapidfuzz import fuzz, process

RAW = Path(__file__).parent.parent / "data" / "raw"
OUT = Path(__file__).parent.parent / "data" / "processed"
OUT.mkdir(exist_ok=True)

FILES = [
    ("2020-21", RAW / "safeguard-facility-data-2020-21.csv", "legacy"),
    ("2021-22", RAW / "safeguard-facility-data-2021-22-0.csv", "legacy"),
    ("2022-23", RAW / "safeguard-facilities-data-2022-23.csv", "legacy"),
    ("2023-24", RAW / "2023-24-baselines-and-emissions-table.csv", "reformed"),
    ("2024-25", RAW / "baselines-and-emissions-table-2024-25.csv", "reformed"),
]

def clean_num(x):
    if pd.isna(x):
        return None
    s = str(x).strip()
    if s in ("", "-", "n/a", "N/A"):
        return None
    s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None

def clean_name(name):
    """Strip numbering prefixes ('1. ', '2. ') and whitespace for matching."""
    s = re.sub(r"^\s*\d+\.\s*", "", str(name)).strip()
    s = re.sub(r"\s+", " ", s)
    return s

def clean_abn(x):
    if pd.isna(x):
        return None
    return re.sub(r"\D", "", str(x))

def load_year(year, path, mechanism):
    # try encodings in order
    df = None
    for enc in ("utf-8-sig", "cp1252", "latin1"):
        try:
            df = pd.read_csv(path, encoding=enc)
            break
        except UnicodeDecodeError:
            continue
    if df is None:
        raise RuntimeError(f"Could not decode {path}")

    df.columns = [c.strip() for c in df.columns]

    if mechanism == "legacy":
        out = pd.DataFrame({
            "facility_name_raw": df["Facility name"],
            "responsible_emitter": df["Responsible emitter"],
            "state": df["State of operation"],
            "anzsic": None,
            "abn": df["Responsible emitter ABN/ACN"].apply(clean_abn),
            "baseline": df[[c for c in df.columns if "Baseline number" in c][0]].apply(clean_num),
            "covered_emissions": df["Reported covered Emissions"].apply(clean_num),
            "net_emissions": df[[c for c in df.columns if c.strip() == "Net emissions number"][0]].apply(clean_num),
            "mymp_baseline": df[[c for c in df.columns if "MYMP baseline number" in c][0]].apply(clean_num),
            "mymp_net_emissions": df["MYMP net emissions number"].apply(clean_num),
            "notes": df["Notes"],
        })
    else:
        out = pd.DataFrame({
            "facility_name_raw": df["Facility name"],
            "responsible_emitter": df["Responsible emitter"],
            "state": df["State/Territory of operation"],
            "anzsic": df["ANZSIC"],
            "abn": None,
            "baseline": df["Baseline emissions number"].apply(clean_num),
            "covered_emissions": df["Covered emissions"].apply(clean_num),
            "net_emissions": df["Net emissions number"].apply(clean_num),
            "mymp_baseline": None,
            "mymp_net_emissions": df["Cumulative MYMP net emissions number"].apply(clean_num),
            "notes": df["Notes"],
        })

    out["year"] = year
    out["mechanism"] = mechanism
    out["facility_name_clean"] = out["facility_name_raw"].apply(clean_name)
    out = out.dropna(subset=["facility_name_raw"]).reset_index(drop=True)
    return out

years_data = {year: load_year(year, path, mech) for year, path, mech in FILES}
for y, d in years_data.items():
    print(y, len(d), "rows")

# ---- Entity resolution across years ----
# Walk years newest -> oldest, matching each earlier-year facility to an
# existing canonical entity (fuzzy match on cleaned name, tie-broken by
# responsible emitter similarity), or creating a new one.

YEAR_ORDER = ["2024-25", "2023-24", "2022-23", "2021-22", "2020-21"]

class Canonical:
    _next_id = 1
    def __init__(self, name, emitter):
        self.id = f"F{Canonical._next_id:04d}"
        Canonical._next_id += 1
        self.names = {}       # year -> raw name
        self.emitters = {}    # year -> emitter
        self.match_conf = {}  # year -> match score (100 for the seed year)
        self.anzsic = None
        self.state = None

registry = []  # list[Canonical]

ACCEPT_THRESHOLD = 90        # combined score >= this: auto-accept match
REVIEW_THRESHOLD = 97        # below this (but above accept): flag for human review
EXACT_NAME_THRESHOLD = 98    # name score >= this auto-accepts regardless of emitter --
                              # an (near-)exact facility name match is almost always the
                              # same physical facility even when the reporting entity
                              # changed (ownership handover, JV restructure, etc.); don't
                              # let emitter dissimilarity veto it (this is what originally
                              # split e.g. "Chandala Processing Plant" and "Curtis Island
                              # GLNG Plant" across a change of responsible emitter)

def combined_score(name_a, name_b, emitter_a, emitter_b):
    name_score = fuzz.WRatio(name_a, name_b)
    emitter_score = fuzz.token_sort_ratio(str(emitter_a).lower(), str(emitter_b).lower())
    # name carries most of the weight; matching emitter nudges borderline cases up,
    # a very different emitter pulls a borderline name match back down
    return name_score, 0.75 * name_score + 0.25 * emitter_score

for year in YEAR_ORDER:
    df = years_data[year]
    for _, row in df.iterrows():
        cname = row["facility_name_clean"]
        emitter = row["responsible_emitter"]
        state = row["state"]

        candidates = [c for c in registry if year not in c.names]

        best = None
        best_score = -1
        for cand in candidates:
            last_year = next(y for y in YEAR_ORDER if y in cand.names)
            cand_name = clean_name(cand.names[last_year])
            cand_emitter = cand.emitters[last_year]
            name_score, score = combined_score(cname, cand_name, emitter, cand_emitter)
            if name_score >= EXACT_NAME_THRESHOLD and state in cand.state:
                score = max(score, ACCEPT_THRESHOLD)  # exact-name bypass, still same-state gated
            # require state overlap to avoid cross-state false matches, unless the
            # combined score is high enough that it's almost certainly the same site
            if state not in cand.state and score < 96:
                continue
            if score > best_score:
                best_score = score
                best = cand

        if best is None or best_score < ACCEPT_THRESHOLD:
            c = Canonical(cname, emitter)
            c.state = {state}
            registry.append(c)
            best = c
            best_score = 100
        else:
            best.state.add(state)

        best.names[year] = row["facility_name_raw"]
        best.emitters[year] = row["responsible_emitter"]
        best.match_conf[year] = best_score
        if pd.notna(row["anzsic"]) and row["anzsic"]:
            best.anzsic = row["anzsic"]

print(f"\nResolved {len(registry)} canonical facilities across {len(YEAR_ORDER)} years")

# ---- Build master facilities table ----
rows = []
for c in registry:
    latest_year = next((y for y in YEAR_ORDER if y in c.names), None)
    row = {
        "facility_id": c.id,
        "canonical_name": c.names[latest_year],
        "latest_year_present": latest_year,
        "responsible_emitter": c.emitters[latest_year],
        "anzsic": c.anzsic,
        "state": sorted(c.state),
        "years_present": ",".join(y for y in YEAR_ORDER if y in c.names),
        "n_years": len(c.names),
        "min_match_confidence": min(c.match_conf.values()),
        "needs_review": min(c.match_conf.values()) < REVIEW_THRESHOLD,
        "latitude": None,
        "longitude": None,
        "geocode_confidence": None,
    }
    for y in YEAR_ORDER:
        row[f"name_{y}"] = c.names.get(y, "")
    rows.append(row)

master = pd.DataFrame(rows)
master["state"] = master["state"].apply(lambda s: "/".join(s))
master = master.sort_values("canonical_name").reset_index(drop=True)
master.to_csv(OUT / "facilities_master.csv", index=False)
print(f"Wrote {OUT / 'facilities_master.csv'} ({len(master)} facilities)")
print(f"  -> {master['needs_review'].sum()} flagged for name-match review")

# ---- Build long emissions table ----
long_rows = []
id_by_year_name = {}
for c in registry:
    for y, raw_name in c.names.items():
        id_by_year_name[(y, raw_name)] = c.id

for year, df in years_data.items():
    for _, row in df.iterrows():
        fid = id_by_year_name.get((year, row["facility_name_raw"]))
        long_rows.append({
            "facility_id": fid,
            "year": year,
            "mechanism": row["mechanism"],
            "facility_name": row["facility_name_raw"],
            "responsible_emitter": row["responsible_emitter"],
            "state": row["state"],
            "anzsic": row["anzsic"],
            "baseline": row["baseline"],
            "covered_emissions": row["covered_emissions"],
            "net_emissions": row["net_emissions"],
            "mymp_baseline": row["mymp_baseline"],
            "mymp_net_emissions": row["mymp_net_emissions"],
            "notes": row["notes"],
        })

emissions_long = pd.DataFrame(long_rows)
emissions_long.to_csv(OUT / "emissions_long.csv", index=False)
print(f"Wrote {OUT / 'emissions_long.csv'} ({len(emissions_long)} facility-year rows)")
