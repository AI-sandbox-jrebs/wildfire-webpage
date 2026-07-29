"""Fetch current wildfire and rainfall data into data/ as GeoJSON/JSON.

Sources (all keyless):
  - NIFC WFIGS current incident locations (US, ArcGIS REST)
  - NASA EONET open wildfire events (global)
  - Open-Meteo (recent + forecast precipitation at each fire)
"""

import json
import math
import pathlib
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"
WFIGS_URL = (
    "https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/"
    "WFIGS_Incident_Locations_Current/FeatureServer/0/query"
)
EONET_URL = "https://eonet.gsfc.nasa.gov/api/v3/events"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

MIN_ACRES = 100

US_STATES = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA",
    "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE", "Florida": "FL", "Georgia": "GA",
    "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA",
    "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC",
    "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT", "Vermont": "VT",
    "Virginia": "VA", "Washington": "WA", "West Virginia": "WV", "Wisconsin": "WI",
    "Wyoming": "WY",
}
RAINFALL_SAMPLE_LIMIT = 120


def get_json(url, params=None, retries=3):
    if params:
        url = f"{url}?{urlencode(params)}"
    last = None
    for attempt in range(retries):
        try:
            req = Request(url, headers={"User-Agent": "wildfire-rainfall-map/1.0"})
            with urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except Exception as exc:  # noqa: BLE001 - network flakiness is expected
            last = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"failed to fetch {url}: {last}")


def valid_coords(lon, lat):
    return (
        isinstance(lon, (int, float))
        and isinstance(lat, (int, float))
        and -180 <= lon <= 180
        and -90 <= lat <= 90
    )


def ms_to_iso(value):
    if not value:
        return None
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()


def fetch_wfigs():
    features = []
    offset = 0
    while True:
        page = get_json(
            WFIGS_URL,
            {
                "where": f"IncidentSize>={MIN_ACRES} AND IncidentTypeCategory='WF'",
                "outFields": ",".join(
                    [
                        "IncidentName",
                        "IncidentSize",
                        "PercentContained",
                        "POOState",
                        "FireDiscoveryDateTime",
                        "FireCause",
                        "IncidentTypeCategory",
                    ]
                ),
                "outSR": 4326,
                "resultOffset": offset,
                "resultRecordCount": 2000,
                "f": "geojson",
            },
        )
        batch = page.get("features", [])
        features.extend(batch)
        if not page.get("properties", {}).get("exceededTransferLimit") or not batch:
            break
        offset += len(batch)

    out = []
    for feat in features:
        geom = feat.get("geometry") or {}
        coords = geom.get("coordinates") or []
        if len(coords) != 2 or not valid_coords(coords[0], coords[1]):
            continue
        props = feat["properties"]
        out.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [round(coords[0], 5), round(coords[1], 5)]},
                "properties": {
                    "source": "WFIGS",
                    "name": (props.get("IncidentName") or "Unnamed fire").title(),
                    "acres": props.get("IncidentSize"),
                    "contained": props.get("PercentContained"),
                    "state": (props.get("POOState") or "").replace("US-", ""),
                    "cause": props.get("FireCause"),
                    "discovered": ms_to_iso(props.get("FireDiscoveryDateTime")),
                },
            }
        )
    return out


def fetch_eonet():
    data = get_json(EONET_URL, {"category": "wildfires", "status": "open", "limit": 1000})
    out = []
    for event in data.get("events", []):
        geoms = [g for g in event.get("geometry", []) if g.get("type") == "Point"]
        if not geoms:
            continue
        latest = geoms[-1]
        lon, lat = (latest["coordinates"] + [None, None])[:2]
        if not valid_coords(lon, lat):
            continue
        acres = latest.get("magnitudeValue") if latest.get("magnitudeUnit") == "acres" else None
        out.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]},
                "properties": {
                    "source": "EONET",
                    "name": event.get("title", "Wildfire").replace("Wildfire ", "").split(",")[0],
                    "acres": acres,
                    "contained": None,
                    "state": US_STATES.get((event.get("title") or "").rsplit(", ", 1)[-1], ""),
                    "cause": None,
                    "discovered": latest.get("date"),
                    "link": event.get("link"),
                },
            }
        )
    return out


def dedupe(features):
    """Drop EONET points that sit within ~15 km of a WFIGS incident."""
    kept = [f for f in features if f["properties"]["source"] == "WFIGS"]
    for feat in features:
        if feat["properties"]["source"] == "WFIGS":
            continue
        lon, lat = feat["geometry"]["coordinates"]
        near = any(
            abs(lat - k["geometry"]["coordinates"][1]) < 0.15
            and abs(lon - k["geometry"]["coordinates"][0]) < 0.15 / max(math.cos(math.radians(lat)), 0.1)
            for k in kept
        )
        if not near:
            kept.append(feat)
    return kept


def fetch_rainfall(feature):
    lon, lat = feature["geometry"]["coordinates"]
    data = get_json(
        OPEN_METEO_URL,
        {
            "latitude": lat,
            "longitude": lon,
            "daily": "precipitation_sum",
            "past_days": 7,
            "forecast_days": 3,
            "timezone": "UTC",
        },
        retries=2,
    )
    daily = data.get("daily", {})
    values = [v if v is not None else 0.0 for v in daily.get("precipitation_sum", [])]
    return {
        "days": daily.get("time", []),
        "precip_mm": [round(v, 2) for v in values],
        "past_7d_mm": round(sum(values[:7]), 2),
        "next_3d_mm": round(sum(values[7:]), 2),
    }


def attach_rainfall(features):
    ranked = sorted(features, key=lambda f: f["properties"].get("acres") or 0, reverse=True)
    targets = ranked[:RAINFALL_SAMPLE_LIMIT]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda f: _safe_rain(f), targets))
    for feat, rain in zip(targets, results):
        if rain:
            feat["properties"]["rain"] = rain
    return targets


def _safe_rain(feature):
    try:
        return fetch_rainfall(feature)
    except Exception as exc:  # noqa: BLE001
        print(f"  rainfall lookup failed for {feature['properties']['name']}: {exc}", file=sys.stderr)
        return None


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print("fetching WFIGS incidents...")
    wfigs = fetch_wfigs()
    print(f"  {len(wfigs)} US incidents >= {MIN_ACRES} acres")
    print("fetching EONET events...")
    eonet = fetch_eonet()
    print(f"  {len(eonet)} global events")

    features = dedupe(wfigs + eonet)
    print("fetching rainfall for largest fires...")
    with_rain = attach_rainfall(features)

    collection = {
        "type": "FeatureCollection",
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "features": features,
    }
    (DATA_DIR / "fires.geojson").write_text(json.dumps(collection))

    acres = [f["properties"]["acres"] or 0 for f in features]
    dry = [
        f["properties"]["name"]
        for f in with_rain
        if f["properties"].get("rain", {}).get("past_7d_mm", 0) < 1
    ]
    summary = {
        "generated": collection["generated"],
        "fire_count": len(features),
        "us_count": sum(1 for f in features if f["properties"]["source"] == "WFIGS"),
        "total_acres": round(sum(acres)),
        "largest": max(
            (f["properties"] for f in features), key=lambda p: p.get("acres") or 0, default={}
        ).get("name"),
        "rainfall_sampled": sum(1 for f in with_rain if "rain" in f["properties"]),
        "dry_fire_count": len(dry),
    }
    (DATA_DIR / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
