"""Regenerate data/cities.json from the GeoNames cities15000 dump.

Run manually when the city list needs refreshing; the output is committed so the
per-build fetch stays small and deterministic.

Source: https://download.geonames.org/export/dump/ (CC BY 4.0)
"""

import csv
import io
import json
import pathlib
import sys
import zipfile
from urllib.request import Request, urlopen

DUMP_URL = "https://download.geonames.org/export/dump/cities15000.zip"
OUT = pathlib.Path(__file__).resolve().parent.parent / "data" / "cities.json"

# Neighborhood-level entries (PPLX) are excluded so sections of a city aren't
# counted on top of the city itself.
KEEP_FEATURE_CODES = {"PPL", "PPLA", "PPLA2", "PPLA3", "PPLA4", "PPLA5", "PPLC", "PPLL", "PPLS"}

# The five NYC boroughs are listed as county seats (PPLA2) *and* rolled into the
# New York City entry, so keeping both would double-count ~7.9M people.
EXCLUDE = {("Brooklyn", "NY"), ("Queens", "NY"), ("Manhattan", "NY"), ("The Bronx", "NY"), ("Staten Island", "NY")}


def main():
    req = Request(DUMP_URL, headers={"User-Agent": "wildfire-rainfall-map/1.0"})
    with urlopen(req, timeout=120) as resp:
        blob = resp.read()

    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        raw = zf.read("cities15000.txt").decode("utf-8")

    cities = []
    for row in csv.reader(io.StringIO(raw), delimiter="\t", quoting=csv.QUOTE_NONE):
        if len(row) < 15 or row[8] != "US" or row[7] not in KEEP_FEATURE_CODES:
            continue
        if (row[1], row[10]) in EXCLUDE:
            continue
        try:
            population = int(row[14])
        except ValueError:
            continue
        if population <= 0:
            continue
        cities.append(
            {
                "n": row[1],
                "s": row[10],  # state (FIPS admin1 code)
                "lat": round(float(row[4]), 4),
                "lon": round(float(row[5]), 4),
                "p": population,
            }
        )

    cities.sort(key=lambda c: c["p"], reverse=True)
    OUT.write_text(json.dumps({"source": "GeoNames cities15000 (CC BY 4.0)", "cities": cities}))
    print(f"wrote {len(cities)} US cities to {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
