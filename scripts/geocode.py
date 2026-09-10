"""
Best-effort geocoding of facilities_master.csv using OpenStreetMap Nominatim.

There is no address data in the source files -- only a state abbreviation --
so this is a name-based search (e.g. "Blackwater Coal Mine, QLD, Australia").
Expect a moderate hit rate; every result is confidence-scored and the sheet
is meant to be spot-checked/corrected by hand, not trusted blindly.

Respects Nominatim's usage policy: <=1 req/sec, identifying User-Agent,
results cached to disk so re-runs don't re-hit the API.
"""
import json
import re
import time
from pathlib import Path

import pandas as pd
import requests

OUT = Path(__file__).parent.parent / "data" / "processed"
CACHE_PATH = OUT / "geocode_cache.json"

STATE_NAMES = {
    "NSW": "New South Wales", "VIC": "Victoria", "QLD": "Queensland",
    "SA": "South Australia", "WA": "Western Australia", "TAS": "Tasmania",
    "NT": "Northern Territory", "ACT": "Australian Capital Territory",
}

HEADERS = {"User-Agent": "bze-safeguard-map-research/1.0 (contact: fred.hiskens@bze.org.au)"}

def load_cache():
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text())
    return {}

def save_cache(cache):
    CACHE_PATH.write_text(json.dumps(cache, indent=1))

def clean_query_name(name):
    # drop numbering prefixes, and generic corporate suffixes that hurt free-text search
    s = re.sub(r"^\s*\d+\.\s*", "", name)
    s = re.sub(r"\bPty\.?\s*Ltd\.?\b", "", s, flags=re.I)
    return s.strip(" -")

def nominatim_search(query):
    resp = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": query, "format": "jsonv2", "countrycodes": "au", "limit": 3, "addressdetails": 1},
        headers=HEADERS,
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()

def score_result(result, expected_state):
    addr = result.get("address", {})
    result_state = addr.get("state", "")
    state_ok = expected_state and STATE_NAMES.get(expected_state, "").lower() == result_state.lower()
    place_class = result.get("class", "")
    place_type = result.get("type", "")
    # a hit on an actual site/facility/industrial feature is worth more than a
    # generic administrative boundary or road match
    specific = place_class in ("landuse", "industrial", "man_made", "building", "amenity", "shop", "office") or \
        place_type in ("industrial", "mine", "quarry", "landfill", "power", "works")
    importance = result.get("importance", 0)
    if state_ok and specific:
        confidence = "likely"
    elif state_ok:
        confidence = "possible"
    else:
        confidence = "low"
    return confidence

def geocode_facility(name, state, cache):
    key = f"{name}|{state}"
    if key in cache:
        return cache[key]

    query_variants = [
        f"{clean_query_name(name)}, {state}, Australia",
        f"{clean_query_name(name)}, {STATE_NAMES.get(state, state)}, Australia",
    ]
    result_entry = {"lat": None, "lon": None, "confidence": "not found", "matched_query": None, "display_name": None}
    for q in query_variants:
        try:
            results = nominatim_search(q)
        except requests.RequestException as e:
            print(f"  ! request failed for '{q}': {e}")
            results = []
        time.sleep(1.1)  # Nominatim usage policy: max 1 req/sec
        if results:
            top = results[0]
            result_entry = {
                "lat": float(top["lat"]),
                "lon": float(top["lon"]),
                "confidence": score_result(top, state),
                "matched_query": q,
                "display_name": top.get("display_name"),
            }
            if result_entry["confidence"] != "low":
                break
    cache[key] = result_entry
    return result_entry

def main():
    master = pd.read_csv(OUT / "facilities_master.csv")
    cache = load_cache()

    lats, lons, confs, disp_names = [], [], [], []
    for i, row in master.iterrows():
        state = str(row["state"]).split("/")[0]
        name = row["canonical_name"]
        print(f"[{i+1}/{len(master)}] {name} ({state}) ...", end=" ")
        result = geocode_facility(name, state, cache)
        print(result["confidence"])
        lats.append(result["lat"])
        lons.append(result["lon"])
        confs.append(result["confidence"])
        disp_names.append(result["display_name"])
        if i % 20 == 0:
            save_cache(cache)

    save_cache(cache)
    master["latitude"] = lats
    master["longitude"] = lons
    master["geocode_confidence"] = confs
    master["geocode_matched_place"] = disp_names
    master.to_csv(OUT / "facilities_master.csv", index=False)

    print("\nGeocode confidence breakdown:")
    print(master["geocode_confidence"].value_counts())

if __name__ == "__main__":
    main()
