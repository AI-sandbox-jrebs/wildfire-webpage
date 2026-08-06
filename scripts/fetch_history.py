"""Refresh long-run fire, climate, drought, and mapped-burn history."""

import json
import csv
import io
import re
import sys
import time
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUTPUT = DATA_DIR / "longterm.json"

NIFC_URL = "https://www.nifc.gov/fire-information/statistics/wildfires"
NOAA_BASE = (
    "https://www.ncei.noaa.gov/access/monitoring/climate-at-a-glance/"
    "national/time-series/110"
)
USDM_URL = "https://usdmdataservices.unl.edu/api/USStatistics/GetBasicStatisticsByAreaPercent"
MTBS_URL = "https://apps.fs.usda.gov/arcx/rest/services/EDW/EDW_MTBS_01/MapServer/63/query"
LAST_COMPLETE_YEAR = datetime.now(timezone.utc).year - 1
TOP_TEN_RECENT_YEAR = 2005

SOURCE_META = {
    "nifc": {
        "name": "NIFC annual wildfire statistics",
        "landing_page": "https://www.nifc.gov/fire-information/statistics/wildfires",
        "geography": "United States",
        "units": "fires and acres",
        "aggregation": "Annual national totals from the official HTML table.",
        "caveats": [
            "There is no official national series before 1983.",
            "2004 excludes North Carolina state lands.",
            "1983–84 fire counts reflect incomplete early reporting and are flagged.",
        ],
    },
    "noaa_pcp": {
        "name": "NOAA NCEI Climate at a Glance precipitation",
        "landing_page": "https://www.ncei.noaa.gov/access/monitoring/climate-at-a-glance/national",
        "geography": "Contiguous United States",
        "units": "inches",
        "aggregation": "Annual January–December value.",
        "caveats": ["Contiguous US only; annual January–December values."],
    },
    "noaa_tavg": {
        "name": "NOAA NCEI Climate at a Glance average temperature",
        "landing_page": "https://www.ncei.noaa.gov/access/monitoring/climate-at-a-glance/national",
        "geography": "Contiguous United States",
        "units": "degrees Fahrenheit",
        "aggregation": "Annual January–December average.",
        "caveats": ["Contiguous US only; annual January–December values."],
    },
    "noaa_zndx": {
        "name": "NOAA NCEI Climate at a Glance Palmer Z-Index",
        "landing_page": "https://www.ncei.noaa.gov/access/monitoring/climate-at-a-glance/national",
        "geography": "Contiguous United States",
        "units": "Palmer Z-Index",
        "aggregation": "Annual January–December value.",
        "caveats": ["This is a Palmer Z-Index, not Palmer Drought Severity Index."],
    },
    "usdm": {
        "name": "U.S. Drought Monitor",
        "landing_page": "https://droughtmonitor.unl.edu/DmData/DataDownload/WebServiceInfo.aspx",
        "geography": "Contiguous United States",
        "units": "percent of US area in D1 or worse",
        "aggregation": "Annual mean of weekly D1-or-worse area percentages, including the boundary week immediately before January 1.",
        "caveats": [
            "Begins in 2000.",
            "Drought categories have different first-observed dates.",
        ],
    },
    "mtbs": {
        "name": "MTBS mapped burned area",
        "landing_page": "https://www.mtbs.gov/direct-download",
        "geography": "United States mapped fire events",
        "units": "acres",
        "aggregation": "Annual sum of mapped event acreage.",
        "caveats": [
            "A mapped burned-area product with its own size, selection, and assessment criteria.",
            "Not interchangeable with NIFC all-wildland-fire totals; never sum or merge the series.",
            "The current year is excluded because it is incomplete.",
        ],
    },
}


def fetch_bytes(url, headers=None, retries=3):
    last = None
    for attempt in range(retries):
        try:
            request_headers = {"User-Agent": "wildfire-rainfall-history/1.0"}
            request_headers.update(headers or {})
            with urlopen(Request(url, headers=request_headers), timeout=90) as response:
                return response.read()
        except Exception as exc:  # noqa: BLE001 - upstreams are optional
            last = exc
            if attempt + 1 < retries:
                time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"{type(last).__name__}: {last}")


class NifcTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.current = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.current = []
        elif tag in ("th", "td") and self.current is not None:
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("th", "td") and self.cell is not None:
            self.current.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.current:
            self.rows.append(self.current)
            self.current = None


def parse_nifc_table(html):
    parser = NifcTableParser()
    parser.feed(html)
    records = []
    for row in parser.rows:
        if len(row) != 3 or not re.fullmatch(r"\d{4}", row[0]):
            continue
        acres = row[2].replace(",", "").replace("*", "")
        try:
            fires = int(row[1].replace(",", ""))
            acres_value = int(acres)
            records.append(
                {
                    "year": int(row[0]),
                    "fires": fires,
                    "acres": acres_value,
                    "acres_per_fire": round(acres_value / fires, 1) if int(row[0]) >= 1985 and fires else None,
                    "count_flag": int(row[0]) < 1985,
                }
            )
        except ValueError:
            continue
    records.sort(key=lambda record: record["year"])
    if len(records) < 40 or records[0]["year"] != 1983:
        raise ValueError("NIFC table was missing a complete annual history")
    return records


def parse_noaa(payload, parameter):
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        raise ValueError(f"NOAA {parameter} response did not contain data")
    records = []
    for key, item in payload["data"].items():
        if not re.fullmatch(r"\d{6}", key) or key[4:] != "12":
            continue
        if not isinstance(item, dict) or not isinstance(item.get("value"), (int, float)):
            continue
        records.append({"year": int(key[:4]), "value": item["value"]})
    records.sort(key=lambda record: record["year"])
    if len(records) < 100 or records[0]["year"] != 1895:
        raise ValueError(f"NOAA {parameter} response was unexpectedly short")
    return records


def parse_usdm(payload):
    if not isinstance(payload, list):
        raise ValueError("USDM response was not a JSON list")
    weekly = []
    for item in payload:
        try:
            if item.get("usdmLevel", item.get("USDMLevel")) != "D1":
                continue
            map_date = date.fromisoformat(item["mapDate"][:10])
            weekly.append((map_date, float(item["areaCurrentPercent"])))
        except (KeyError, TypeError, ValueError):
            continue
    if len(weekly) < 500:
        raise ValueError("USDM response was unexpectedly short")
    weekly.sort()
    annual = {}
    for index, (map_date, value) in enumerate(weekly):
        annual.setdefault(map_date.year, []).append(value)
        if index and map_date.month == 1 and map_date.day <= 7:
            annual[map_date.year].append(weekly[index - 1][1])
    records = [{"year": year, "value": round(sum(values) / len(values), 2)} for year, values in sorted(annual.items())]
    if len(records) < 20 or records[0]["year"] != 2000:
        raise ValueError("USDM response did not cover the expected annual range")
    return records


def parse_usdm_bytes(raw):
    try:
        return parse_usdm(json.loads(raw))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        rows = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        payload = [
            {
                "mapDate": row.get("MapDate"),
                "areaCurrentPercent": row.get("AreaCurrentPercent"),
                "usdmLevel": row.get("USDMLevel"),
            }
            for row in rows
        ]
        return parse_usdm(payload)


def parse_mtbs(payload, end_year):
    features = (payload or {}).get("features") if isinstance(payload, dict) else None
    if not features:
        raise ValueError("MTBS response contained no grouped records")
    records = []
    for feature in features:
        attrs = feature.get("attributes", {})
        year = attrs.get("year")
        acres = attrs.get("acres_sum")
        if isinstance(year, int) and year <= end_year and isinstance(acres, (int, float)):
            records.append({"year": year, "acres": round(acres), "mapped_events": attrs.get("event_count")})
    records.sort(key=lambda record: record["year"])
    if len(records) < 30 or records[0]["year"] != 1984:
        raise ValueError("MTBS response was unexpectedly short")
    return records


def series_metadata(key, source_url, records, last_success):
    meta = dict(SOURCE_META[key])
    meta.update(
        {
            "source": SOURCE_META[key]["name"],
            "url": source_url,
            "coverage_start": records[0]["year"],
            "coverage_end": records[-1]["year"],
            "last_success": last_success,
            "status": "ok",
        }
    )
    if key == "noaa_pcp":
        baseline = sum(record["value"] for record in records) / len(records)
        meta["baseline"] = round(baseline, 2)
        meta["baseline_period"] = f"{records[0]['year']}–{records[-1]['year']}"
    return meta


def build_derived(nifc, all_series=None):
    valid_count_records = [record for record in nifc if record["year"] >= 1985]
    by_year = {record["year"]: record for record in nifc}
    decade_ranges = [(1983, 1989), (1990, 1999), (2000, 2009), (2010, 2019), (2020, nifc[-1]["year"])]
    decades = []
    for start, end in decade_ranges:
        records = [record for record in nifc if start <= record["year"] <= end]
        count_records = [record for record in records if record["year"] >= 1985]
        avg_fires = round(sum(record["fires"] for record in count_records) / len(count_records)) if count_records else None
        avg_acres = round(sum(record["acres"] for record in records) / len(records)) if records else None
        acres_per_fire = (
            round(
                sum(record["acres"] for record in count_records)
                / sum(record["fires"] for record in count_records),
                1,
            )
            if count_records and sum(record["fires"] for record in count_records)
            else None
        )
        decades.append(
            {
                "label": f"{start}–{end}",
                "start": start,
                "end": end,
                "avg_fires": avg_fires,
                "avg_acres": avg_acres,
                "acres_per_fire": acres_per_fire,
                "fire_years_used": [record["year"] for record in count_records],
                "count_caveat": "1983–84 excluded from count averages because early reporting was incomplete."
                if start == 1983
                else None,
            }
        )
    ranked = sorted(nifc, key=lambda record: record["acres"], reverse=True)
    top_ten = [record["year"] for record in ranked[:10]]
    rank_lookup = {record["year"]: index for index, record in enumerate(ranked, 1)}
    early = [record for record in valid_count_records if 1985 <= record["year"] <= 1989]
    recent = [record for record in valid_count_records if record["year"] >= 2020]
    early_count_label = f"{early[0]['year']}–{early[-1]['year']}"
    recent_count_label = f"{recent[0]['year']}–{recent[-1]['year']}"
    top_10_count = sum(year >= TOP_TEN_RECENT_YEAR for year in top_ten)
    if top_10_count == len(top_ten) and len(top_ten) == 10:
        top_10_sentence = f"All {len(top_ten)} of the ten biggest fire-years came since {TOP_TEN_RECENT_YEAR}"
    elif top_10_count:
        top_10_sentence = f"{top_10_count} of the ten biggest fire-years came since {TOP_TEN_RECENT_YEAR}"
    else:
        top_10_sentence = "None of the ten biggest fire-years came in the recent record"
    early_size = sum(record["acres"] for record in early) / sum(record["fires"] for record in early)
    recent_size = sum(record["acres"] for record in recent) / sum(record["fires"] for record in recent)
    result = {
        "decades": decades,
        "latest_year": nifc[-1]["year"],
        "latest_year_acres_rank": next(index for index, record in enumerate(ranked, 1) if record["year"] == nifc[-1]["year"]),
        "top_10_acre_years": top_ten,
        "top_10_after_2000": sum(year > 2000 for year in top_ten),
        "top_10_since_2005": sum(year >= 2005 for year in top_ten),
        "early_count_average": round(sum(record["fires"] for record in early) / len(early)),
        "recent_count_average": round(sum(record["fires"] for record in recent) / len(recent)),
        "early_acres_per_fire": round(early_size, 1),
        "recent_acres_per_fire": round(recent_size, 1),
        "recent_size_multiplier": round(recent_size / early_size, 1),
        "early_count_label": early_count_label,
        "recent_count_label": recent_count_label,
        "top_10_sentence": top_10_sentence,
        "count_comparison_note": "1983–84 counts are flagged and excluded from count-based comparisons.",
        "acreage_rank_records": [{"year": record["year"], "acres": record["acres"]} for record in ranked],
        "year_lookup": {
            str(year): {
                "fires": by_year[year]["fires"],
                "acres": by_year[year]["acres"],
                "acres_per_fire": round(by_year[year]["acres"] / by_year[year]["fires"], 1)
                if year >= 1985
                else None,
                "count_flag": year < 1985,
                "acre_rank": rank_lookup[year],
            }
            for year in by_year
        },
    }
    if all_series:
        lookup = {record["year"]: dict(record) for record in nifc}
        for key, field in (("noaa_pcp", "precipitation"), ("noaa_tavg", "temperature"), ("usdm", "drought")):
            for record in all_series.get(key, {}).get("records", []):
                lookup.setdefault(record["year"], {})[field] = record["value"]
                if key == "noaa_pcp":
                    lookup[record["year"]]["precipitation_anomaly"] = record.get("anomaly")
        result["year_context"] = {
            str(year): {
                "fires": values.get("fires"),
                "acres": values.get("acres"),
                "acres_per_fire": round(values["acres"] / values["fires"], 1)
                if year >= 1985 and values.get("fires")
                else None,
                "count_flag": year < 1985,
                "acre_rank": rank_lookup[year],
                "precipitation": values.get("precipitation"),
                "precipitation_anomaly": values.get("precipitation_anomaly"),
                "temperature": values.get("temperature"),
                "drought": values.get("drought"),
            }
            for year, values in lookup.items()
            if year in by_year
        }
    return result


def load_existing():
    try:
        return json.loads(OUTPUT.read_text())
    except (OSError, json.JSONDecodeError):
        return {"generated": None, "series": {}, "sources": {}}


def refresh_source(output, previous, key, fetcher, now):
    old_series = previous.get("series", {}).get(key)
    old_source = previous.get("sources", {}).get(key, {})
    try:
        records, source_url = fetcher()
        metadata = series_metadata(key, source_url, records, now)
        output["series"][key] = {"metadata": metadata, "records": records}
        output["sources"][key] = {"status": "ok", "last_success": now, "metadata": metadata}
        return True
    except Exception as exc:  # noqa: BLE001 - each historical source is optional
        if old_series and old_series.get("records"):
            output["series"][key] = old_series
        metadata = dict(old_series.get("metadata", {})) if old_series else dict(SOURCE_META[key])
        output["sources"][key] = {
            "status": "failed",
            "last_success": old_source.get("last_success") or old_series.get("metadata", {}).get("last_success")
            if old_series
            else old_source.get("last_success"),
            "error": str(exc),
            "metadata": metadata,
        }
        print(f"{key}: unavailable ({exc}); keeping previous data", file=sys.stderr)
        return False


def make_fetchers(end_year):
    noaa = {}
    for key, parameter in (("noaa_pcp", "pcp"), ("noaa_tavg", "tavg"), ("noaa_zndx", "zndx")):
        url = f"{NOAA_BASE}/{parameter}/12/12/1895-{end_year}.json"
        def fetch_noaa(key=key, parameter=parameter, url=url):
            records = parse_noaa(json.loads(fetch_bytes(url)), parameter)
            if key == "noaa_pcp":
                baseline = sum(record["value"] for record in records) / len(records)
                for record in records:
                    record["anomaly"] = round(record["value"] - baseline, 2)
            return records, url
        noaa[key] = fetch_noaa

    usdm_params = {
        "aoi": "CONUS",
        "dx": "1",
        "DxLevelThresholdFrom": "0",
        "DxLevelThresholdTo": "100",
        "startdate": "1/1/2000",
        "enddate": f"12/31/{end_year}",
        "statisticsType": "1",
    }
    usdm_url = f"{USDM_URL}?{urlencode(usdm_params)}"
    mtbs_stats = json.dumps(
        [
            {"statisticType": "count", "onStatisticField": "objectid", "outStatisticFieldName": "event_count"},
            {"statisticType": "sum", "onStatisticField": "acres", "outStatisticFieldName": "acres_sum"},
        ],
        separators=(",", ":"),
    )
    mtbs_params = {
        "where": f"year <= {end_year}",
        "outStatistics": mtbs_stats,
        "groupByFieldsForStatistics": "year",
        "orderByFields": "year ASC",
        "returnGeometry": "false",
        "f": "json",
    }
    mtbs_url = f"{MTBS_URL}?{urlencode(mtbs_params)}"
    return {
        "nifc": lambda: (parse_nifc_table(fetch_bytes(NIFC_URL, {"User-Agent": "Mozilla/5.0 (history; wildfire-rainfall-map)"}).decode("utf-8", "replace")), NIFC_URL),
        **noaa,
        "usdm": lambda: (parse_usdm_bytes(fetch_bytes(usdm_url)), usdm_url),
        "mtbs": lambda: (parse_mtbs(json.loads(fetch_bytes(mtbs_url)), end_year), mtbs_url),
    }


def main():
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    previous = load_existing()
    output = {"generated": now, "series": {}, "sources": {}}
    fetchers = make_fetchers(LAST_COMPLETE_YEAR)
    for key in SOURCE_META:
        refresh_source(output, previous, key, fetchers[key], now)

    nifc = output["series"].get("nifc", {}).get("records")
    if nifc:
        output["derived"] = build_derived(nifc, output["series"])
    elif previous.get("derived"):
        output["derived"] = previous["derived"]
    if not output["series"]:
        print("no historical sources available and no previous longterm.json", file=sys.stderr)
        return 1
    OUTPUT.write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
