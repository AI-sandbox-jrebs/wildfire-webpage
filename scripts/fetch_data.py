"""Fetch current wildfire and rainfall data into data/ as GeoJSON/JSON.

Sources (all keyless):
  - NIFC WFIGS current incident locations (US, ArcGIS REST)
  - Open-Meteo (recent + forecast precipitation at each fire)
"""

import json
import pathlib
import sys
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"
WFIGS_URL = (
    "https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/"
    "WFIGS_Incident_Locations_Current/FeatureServer/0/query"
)
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
HMS_SMOKE_URL = (
    "https://satepsanone.nesdis.noaa.gov/pub/FIRE/web/HMS/Smoke_Polygons/KML/"
    "{y}/{m}/hms_smoke{y}{m}{d}.kml"
)

# Growth is reported only against a genuinely recorded snapshot in this age
# window — never interpolated or extrapolated.
GROWTH_WINDOW_MIN_HOURS = 18
GROWTH_WINDOW_MAX_HOURS = 36
HISTORY_MAX_POINTS = 120
HISTORY_MAX_AGE_DAYS = 45

MIN_ACRES = 10

RAINFALL_SAMPLE_LIMIT = 120


RATE_LIMIT_BACKOFF_S = 65


def get_json(url, params=None, retries=4):
    if params:
        url = f"{url}?{urlencode(params)}"
    last = None
    for attempt in range(retries):
        try:
            req = Request(url, headers={"User-Agent": "wildfire-rainfall-map/1.0"})
            with urlopen(req, timeout=60) as resp:
                payload = json.load(resp)
            # ArcGIS reports rate limits as HTTP 200 with an error body, which
            # would otherwise be read as "no fires".
            if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
                raise RuntimeError(payload["error"].get("message", "upstream error"))
            return payload
        except Exception as exc:  # noqa: BLE001 - network flakiness is expected
            last = exc
            if attempt == retries - 1:
                break
            # ArcGIS quotas are per minute, so a few seconds of backoff would
            # just burn retries.
            rate_limited = "too many requests" in str(exc).lower() or "429" in str(exc)
            time.sleep(RATE_LIMIT_BACKOFF_S if rate_limited else 2 * (attempt + 1))
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


WFIGS_WHERE = f"IncidentSize>={MIN_ACRES} AND IncidentTypeCategory='WF'"


def wfigs_expected_count():
    return get_json(WFIGS_URL, {"where": WFIGS_WHERE, "returnCountOnly": "true", "f": "json"}).get(
        "count"
    )


def fetch_wfigs():
    # The service can silently return a short page when it is under load, so we
    # ask how many records should exist and verify we actually got them.
    expected = wfigs_expected_count()
    features = []
    offset = 0
    while True:
        page = get_json(
            WFIGS_URL,
            {
                "where": WFIGS_WHERE,
                "outFields": ",".join(
                    [
                        "IrwinID",
                        "UniqueFireIdentifier",
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

    if expected and len(features) < expected:
        raise RuntimeError(f"WFIGS returned {len(features)} of {expected} incidents")

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
                    "id": (props.get("IrwinID") or "").strip("{}").lower()
                    or f"wfigs:{props.get('UniqueFireIdentifier') or props.get('IncidentName')}",
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


# --------------------------------------------------------------------------
# Air quality
# --------------------------------------------------------------------------


def fetch_aqi(feature):
    lon, lat = feature["geometry"]["coordinates"]
    data = get_json(
        AIR_QUALITY_URL,
        {
            "latitude": lat,
            "longitude": lon,
            "current": "us_aqi,pm2_5",
            "timezone": "UTC",
        },
        retries=2,
    )
    current = data.get("current") or {}
    aqi = current.get("us_aqi")
    if aqi is None:
        return None
    return {"us_aqi": round(aqi), "pm2_5": current.get("pm2_5")}


def attach_aqi(features):
    """Sample air quality at the largest fires (same cohort as rainfall)."""
    targets = sorted(features, key=lambda f: f["properties"].get("acres") or 0, reverse=True)[
        :RAINFALL_SAMPLE_LIMIT
    ]

    def safe(feature):
        try:
            return fetch_aqi(feature)
        except Exception as exc:  # noqa: BLE001
            print(f"  aqi lookup failed for {feature['properties']['name']}: {exc}", file=sys.stderr)
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(safe, targets))
    attached = 0
    for feature, aqi in zip(targets, results):
        if aqi:
            feature["properties"]["aqi"] = aqi
            attached += 1
    return attached


# --------------------------------------------------------------------------
# Smoke plumes (NOAA HMS)
# --------------------------------------------------------------------------

KML_NS = {"k": "http://www.opengis.net/kml/2.2"}
SMOKE_DENSITIES = {"Smoke (Light)": "Light", "Smoke (Medium)": "Medium", "Smoke (Heavy)": "Heavy"}


def _parse_kml_coords(text):
    ring = []
    for chunk in text.split():
        parts = chunk.split(",")
        if len(parts) < 2:
            continue
        try:
            lon, lat = float(parts[0]), float(parts[1])
        except ValueError:
            continue
        if valid_coords(lon, lat):
            ring.append([round(lon, 4), round(lat, 4)])
    return ring


def fetch_smoke():
    """NOAA HMS smoke plumes for the most recent day that has been published."""
    now = datetime.now(timezone.utc)
    last_error = None
    for days_back in range(0, 3):
        day = now - timedelta(days=days_back)
        url = HMS_SMOKE_URL.format(y=day.strftime("%Y"), m=day.strftime("%m"), d=day.strftime("%d"))
        try:
            req = Request(url, headers={"User-Agent": "wildfire-rainfall-map/1.0"})
            with urlopen(req, timeout=90) as resp:
                raw = resp.read()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            continue

        features = []
        root = ET.fromstring(raw)
        for folder in root.iter(f"{{{KML_NS['k']}}}Folder"):
            name_el = folder.find("k:name", KML_NS)
            density = SMOKE_DENSITIES.get(name_el.text.strip() if name_el is not None and name_el.text else "")
            if not density:
                continue
            for polygon in folder.iter(f"{{{KML_NS['k']}}}Polygon"):
                rings = []
                outer = polygon.find(".//k:outerBoundaryIs//k:coordinates", KML_NS)
                if outer is None or not outer.text:
                    continue
                ring = _parse_kml_coords(outer.text)
                if len(ring) < 4:
                    continue
                rings.append(ring)
                for inner in polygon.findall(".//k:innerBoundaryIs//k:coordinates", KML_NS):
                    hole = _parse_kml_coords(inner.text or "")
                    if len(hole) >= 4:
                        rings.append(hole)
                features.append(
                    {
                        "type": "Feature",
                        "geometry": {"type": "Polygon", "coordinates": rings},
                        "properties": {"density": density},
                    }
                )

        if features:
            return {
                "type": "FeatureCollection",
                "analysis_date": day.strftime("%Y-%m-%d"),
                "age_days": days_back,
                "features": features,
            }
        last_error = RuntimeError("no smoke polygons in KML")

    raise RuntimeError(f"no HMS smoke product available: {last_error}")


def _point_in_ring(lon, lat, ring):
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        if (y1 > lat) != (y2 > lat):
            x_at = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
            if lon < x_at:
                inside = not inside
    return inside


def _point_in_polygon(lon, lat, rings):
    if not rings or not _point_in_ring(lon, lat, rings[0]):
        return False
    return not any(_point_in_ring(lon, lat, hole) for hole in rings[1:])


def smoke_impact(smoke, cities):
    """Cities (>=15k people) whose center falls inside a smoke plume.

    Deliberately conservative: this counts city centers under a plume, not
    everyone breathing smoke, and it is labelled that way in the UI.
    """
    rank = {"Light": 1, "Medium": 2, "Heavy": 3}
    bboxes = []
    for feature in smoke["features"]:
        rings = feature["geometry"]["coordinates"]
        outer = rings[0]
        lons = [p[0] for p in outer]
        lats = [p[1] for p in outer]
        bboxes.append(
            (min(lons), min(lats), max(lons), max(lats), rings, feature["properties"]["density"])
        )

    affected = {}
    for city in cities:
        lon, lat = city["lon"], city["lat"]
        worst = None
        for min_lon, min_lat, max_lon, max_lat, rings, density in bboxes:
            if not (min_lon <= lon <= max_lon and min_lat <= lat <= max_lat):
                continue
            if rank[density] > rank.get(worst or "", 0) and _point_in_polygon(lon, lat, rings):
                worst = density
                if worst == "Heavy":
                    break
        if worst:
            affected[f"{city['n']}, {city['s']}"] = {
                "name": city["n"],
                "state": city["s"],
                "population": city["p"],
                "density": worst,
            }

    entries = sorted(affected.values(), key=lambda c: c["population"], reverse=True)
    by_density = {d: 0 for d in rank}
    population_by_density = {d: 0 for d in rank}
    for entry in entries:
        by_density[entry["density"]] += 1
        population_by_density[entry["density"]] += entry["population"]

    return {
        "analysis_date": smoke.get("analysis_date"),
        "age_days": smoke.get("age_days", 0),
        "city_count": len(entries),
        "population": sum(e["population"] for e in entries),
        "cities_by_density": by_density,
        "population_by_density": population_by_density,
        "top_cities": entries[:12],
    }


# --------------------------------------------------------------------------
# Growth history
# --------------------------------------------------------------------------


def load_json_file(path, default):
    try:
        return json.loads(path.read_text())
    except Exception:  # noqa: BLE001 - a missing or corrupt file just means no history yet
        return default


def update_history(features, now):
    """Append this run's observation per fire and derive real measured growth."""
    path = DATA_DIR / "history.json"
    store = load_json_file(path, {})
    if not isinstance(store, dict):
        store = {}

    now_iso = now.isoformat(timespec="seconds")
    cutoff = now - timedelta(days=HISTORY_MAX_AGE_DAYS)

    for feature in features:
        props = feature["properties"]
        fire_id = props.get("id")
        acres = props.get("acres")
        if not fire_id or acres is None:
            continue
        points = store.get(fire_id) or []
        # Skip duplicate readings so a stalled upstream feed doesn't look like data.
        if not points or points[-1][1] != acres or points[-1][2] != props.get("contained"):
            points.append([now_iso, acres, props.get("contained")])
        store[fire_id] = points[-HISTORY_MAX_POINTS:]

    live_ids = {f["properties"].get("id") for f in features}
    for fire_id in list(store):
        points = store[fire_id]
        if fire_id not in live_ids and (not points or parse_iso(points[-1][0]) < cutoff):
            del store[fire_id]

    path.write_text(json.dumps(store, separators=(",", ":")))

    measured = 0
    for feature in features:
        props = feature["properties"]
        growth = derive_growth(store.get(props.get("id")) or [], props, now)
        if growth:
            props["growth"] = growth
            measured += 1
        props["burn_rate"] = average_burn_rate(props, now)
    return measured


def average_burn_rate(props, now):
    """Mean acres/day since discovery.

    Available immediately (unlike measured 24 h growth, which needs a day of
    snapshots) but it is a lifetime average, so the UI labels it as such.
    """
    acres = props.get("acres")
    discovered = props.get("discovered")
    if not acres or not discovered:
        return None
    days = (now - parse_iso(discovered)).total_seconds() / 86400
    if days < 1:
        return None
    return round(acres / days, 1)


def parse_iso(value):
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def derive_growth(points, props, now):
    """Growth vs the most recent real snapshot 18-36 h old. None when unknown."""
    if len(points) < 2:
        return None
    acres_now = props.get("acres")
    if acres_now is None:
        return None

    baseline = None
    for stamp, acres, contained in reversed(points[:-1]):
        age_hours = (now - parse_iso(stamp)).total_seconds() / 3600
        if age_hours < GROWTH_WINDOW_MIN_HOURS:
            continue
        if age_hours > GROWTH_WINDOW_MAX_HOURS:
            break
        baseline = (stamp, acres, contained, age_hours)
        break
    if not baseline:
        return None

    _, base_acres, base_contained, age_hours = baseline
    delta = round(acres_now - base_acres, 1)
    growth = {
        "acres_delta": delta,
        "hours": round(age_hours, 1),
        "series": [[stamp, acres] for stamp, acres, _ in points[-40:]],
    }
    if base_acres:
        growth["pct"] = round(delta / base_acres * 100, 1)
    contained_now = props.get("contained")
    if contained_now is not None and base_contained is not None:
        growth["contained_delta"] = round(contained_now - base_contained, 1)
    return growth


def history_start():
    """Timestamp of the oldest recorded snapshot, so the UI can say how far back
    growth figures can possibly reach."""
    store = load_json_file(DATA_DIR / "history.json", {})
    stamps = [points[0][0] for points in store.values() if points]
    return min(stamps) if stamps else None


def write_fires_guarded(collection):
    """Publish fires only if the dataset is plausible.

    A transient upstream error can return zero features; overwriting the map
    with an empty file is far worse than serving the previous run's data.
    Genuine large drops are normal (fires get contained and leave the feed), so
    completeness is checked against the source's own record count in
    fetch_wfigs() rather than against the previous run.
    """
    path = DATA_DIR / "fires.geojson"
    count = len(collection["features"])
    if count == 0:
        print("  no fires returned: keeping previous data", file=sys.stderr)
        return False
    path.write_text(json.dumps(collection))
    return True


def optional(name, status, fn, default=None):
    """Run a non-critical step; record failure instead of aborting the build."""
    try:
        result = fn()
        status[name] = "ok"
        return result
    except Exception as exc:  # noqa: BLE001
        print(f"  {name} unavailable: {exc}", file=sys.stderr)
        status[name] = f"failed: {exc}"
        return default


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    status = {}

    print("fetching WFIGS incidents...")
    wfigs = optional("wfigs", status, fetch_wfigs)
    if wfigs is None:
        # Leave the committed data in place: a stale map still helps people,
        # a failed deploy helps nobody.
        print("WFIGS unavailable; keeping existing data", file=sys.stderr)
        return 0
    print(f"  {len(wfigs)} US incidents >= {MIN_ACRES} acres")
    features = wfigs

    print("fetching rainfall for largest fires...")
    with_rain = optional("rainfall", status, lambda: attach_rainfall(features), default=[])

    print("fetching air quality for largest fires...")
    aqi_count = optional("air_quality", status, lambda: attach_aqi(features), default=0)

    print("recording growth history...")
    growth_count = optional("growth", status, lambda: update_history(features, now), default=0)

    print("fetching NOAA HMS smoke plumes...")
    smoke = optional("smoke", status, fetch_smoke)
    impact = None
    if smoke:
        (DATA_DIR / "smoke.geojson").write_text(json.dumps(smoke, separators=(",", ":")))
        cities = load_json_file(DATA_DIR / "cities.json", {}).get("cities", [])
        if cities:
            impact = optional("smoke_impact", status, lambda: smoke_impact(smoke, cities))
    else:
        # Keep yesterday's plumes rather than blanking the layer, and let the UI
        # age-label them.
        print("  keeping previously fetched smoke.geojson if present", file=sys.stderr)

    collection = {
        "type": "FeatureCollection",
        "generated": now.isoformat(timespec="seconds"),
        "features": features,
    }
    if not write_fires_guarded(collection):
        print("refusing to publish an implausible fire dataset", file=sys.stderr)
        return 1

    acres = [f["properties"]["acres"] or 0 for f in features]
    dry = [
        f["properties"]["name"]
        for f in with_rain
        if f["properties"].get("rain", {}).get("past_7d_mm", 0) < 1
    ]
    growing = sorted(
        (f["properties"] for f in features if (f["properties"].get("growth") or {}).get("acres_delta", 0) > 0),
        key=lambda p: p["growth"]["acres_delta"],
        reverse=True,
    )
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
        "aqi_sampled": aqi_count,
        "growth_measured": growth_count,
        "history_since": history_start(),
        "growing_count": len(growing),
        "acres_gained_24h": round(sum(p["growth"]["acres_delta"] for p in growing)),
        "smoke": impact,
        "sources": status,
    }
    (DATA_DIR / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
