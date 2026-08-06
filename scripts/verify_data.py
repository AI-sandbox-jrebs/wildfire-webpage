"""Build-time checks over the published wildfire and history data."""

import json
import pathlib
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote, urlencode

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"
WFIGS_URL = (
    "https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/"
    "WFIGS_Incident_Locations_Current/FeatureServer/0/query"
)
WFIGS_QUERY_URL = WFIGS_URL + "?" + urlencode(
    {"where": "IncidentSize>=10 AND IncidentTypeCategory='WF'", "returnCountOnly": "true", "f": "json"}
)
MTBS_EXCESS_THRESHOLD = 0.20
MTBS_EXCESS_YEAR_LIMIT = 3

EXPECTED_REFRESH = {
    "current": timedelta(hours=3),
    "history": timedelta(days=8),
}


def _check(check_id, description, status, actual, sources):
    return {
        "id": check_id,
        "description": description,
        "status": status,
        "actual": actual,
        "sources": sources,
    }


def _source_url(metadata):
    return metadata.get("url") if isinstance(metadata, dict) else None


def _parse_time(value):
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _years_are_contiguous(records):
    years = [record.get("year") for record in records]
    return bool(years) and years == list(range(years[0], years[-1] + 1))


def build_verification(summary, longterm, points, now=None):
    now = now or datetime.now(timezone.utc)
    checks = []
    series = longterm.get("series", {})
    nifc_records = series.get("nifc", {}).get("records", [])
    mtbs_records = series.get("mtbs", {}).get("records", [])
    nifc_by_year = {record.get("year"): record for record in nifc_records}
    mtbs_by_year = {record.get("year"): record for record in mtbs_records}
    nifc_url = _source_url(series.get("nifc", {}).get("metadata", {}))
    mtbs_url = _source_url(series.get("mtbs", {}).get("metadata", {}))

    comparisons = [
        {
            "year": year,
            "mtbs_acres": mtbs_by_year[year]["acres"],
            "nifc_acres": nifc_by_year[year]["acres"],
        }
        for year in sorted(set(nifc_by_year) & set(mtbs_by_year))
    ]
    for item in comparisons:
        item["excess_ratio"] = round(item["mtbs_acres"] / item["nifc_acres"] - 1, 4)
    exceeding_years = [item for item in comparisons if item["excess_ratio"] > 0]
    extreme_years = [
        item for item in comparisons if item["excess_ratio"] > MTBS_EXCESS_THRESHOLD
    ]
    excess_status = "fail" if (
        extreme_years or len(exceeding_years) > MTBS_EXCESS_YEAR_LIMIT
    ) else "pass"
    checks.append(
        _check(
            "mtbs-excess-calibration",
            "MTBS sums satellite-mapped fire perimeters, which can enclose unburned patches, while NIFC sums acreage reported by incident. A modest excess is therefore expected; a large one, or many years drifting high at once, means something other than wildfire is being counted.",
            excess_status,
            {
                "comparisons": comparisons,
                "exceeding_years": exceeding_years,
                "extreme_years": extreme_years,
                "excess_threshold": MTBS_EXCESS_THRESHOLD,
                "max_excess_years": MTBS_EXCESS_YEAR_LIMIT,
            },
            [mtbs_url, nifc_url],
        )
    )

    point_url = points.get("metadata", {}).get("url")
    wildfire_filter = all(
        token in unquote(url or "")
        for url in (mtbs_url, point_url)
        for token in ("fire_type='Wildfire'",)
    )
    checks.append(
        _check(
            "mtbs-wildfire-only",
            "Published MTBS records are fetched with an explicit wildfire-only filter.",
            "pass" if wildfire_filter else "fail",
            {"wildfire_filter_present": wildfire_filter, "record_type": "Wildfire"},
            [mtbs_url, point_url],
        )
    )

    latest_year = max(nifc_by_year) if nifc_by_year else None
    provisional = longterm.get("sources", {}).get("mtbs", {}).get("metadata", {}).get(
        "provisional_years",
        series.get("mtbs", {}).get("metadata", {}).get("provisional_years", []),
    )
    old_provisional = [
        year for year in provisional if latest_year is None or year < latest_year - 2
    ]
    checks.append(
        _check(
            "mtbs-provisional-recent",
            "MTBS provisional flags are limited to the newest assessment-lag window.",
            "fail" if old_provisional else "pass",
            {
                "latest_nifc_year": latest_year,
                "provisional_years": provisional,
                "old_provisional_years": old_provisional,
            },
            [mtbs_url, nifc_url],
        )
    )

    count_check = summary.get("wfigs_count_check", {})
    expected_count = count_check.get("source_total", summary.get("wfigs_reported_count"))
    actual_count = count_check.get("fetched_count", summary.get("fire_count"))
    count_status = count_check.get("status", "flag")
    checks.append(
        _check(
            "current-fire-count",
            "Current-fire count is compared with WFIGS's own reported total at build time.",
            count_status,
            {"published_count": actual_count, "wfigs_reported_count": expected_count},
            [WFIGS_QUERY_URL],
        )
    )

    drought_records = series.get("usdm", {}).get("records", [])
    bad_drought = [
        {"year": record.get("year"), "value": record.get("value")}
        for record in drought_records
        if not isinstance(record.get("value"), (int, float)) or not 0 <= record["value"] <= 100
    ]
    drought_url = _source_url(series.get("usdm", {}).get("metadata", {}))
    checks.append(
        _check(
            "drought-range",
            "Published drought percentages stay within 0–100 percent.",
            "fail" if bad_drought else "pass",
            {"invalid_records": bad_drought, "record_count": len(drought_records)},
            [drought_url],
        )
    )

    for key, value in series.items():
        records = value.get("records", [])
        metadata = series.get(key, {}).get("metadata", {})
        checks.append(
            _check(
                f"coverage-{key}",
                f"{key} coverage years are contiguous with no gaps.",
                "pass" if _years_are_contiguous(records) else "fail",
                {
                    "coverage_start": records[0].get("year") if records else None,
                    "coverage_end": records[-1].get("year") if records else None,
                    "record_count": len(records),
                },
                [_source_url(metadata)],
            )
        )

    bad_values = []
    for key, series_data in series.items():
        for record in series_data.get("records", []):
            for field in ("acres", "fires"):
                value = record.get(field)
                if value is not None and (
                    not isinstance(value, (int, float)) or value < 0 or value > 1_000_000_000
                ):
                    bad_values.append({"series": key, "year": record.get("year"), "field": field, "value": value})
            if key == "usdm":
                value = record.get("value")
                if value is not None and (
                    not isinstance(value, (int, float)) or value < 0 or value > 100
                ):
                    bad_values.append({"series": key, "year": record.get("year"), "field": "value", "value": value})
    summary_values = {
        "fire_count": summary.get("fire_count"),
        "total_acres": summary.get("total_acres"),
    }
    for field, value in summary_values.items():
        if value is not None and (not isinstance(value, (int, float)) or value < 0 or value > 1_000_000_000):
            bad_values.append({"series": "summary", "field": field, "value": value})
    checks.append(
        _check(
            "plausible-values",
            "Published acreage, count, and percentage values are numeric and within broad plausible bounds.",
            "fail" if bad_values else "pass",
            {"invalid_values": bad_values},
            [_source_url(series.get("nifc", {}).get("metadata", {})), WFIGS_QUERY_URL],
        )
    )

    missing_provenance = []
    for key, source in longterm.get("sources", {}).items():
        metadata = source.get("metadata", {})
        if not metadata.get("url") or not source.get("last_success"):
            missing_provenance.append(key)
    if not points.get("metadata", {}).get("url") or not points.get("metadata", {}).get("last_success"):
        missing_provenance.append("points")
    checks.append(
        _check(
            "source-provenance",
            "Every published historical source carries a rerunnable URL and last-success timestamp.",
            "fail" if missing_provenance else "pass",
            {"missing_sources": missing_provenance},
            [
                *[_source_url(source.get("metadata", {})) for source in longterm.get("sources", {}).values()],
                _source_url(points.get("metadata", {})),
            ],
        )
    )

    stale = []
    for key, source in longterm.get("sources", {}).items():
        stamp = _parse_time(source.get("last_success"))
        if stamp and now - stamp > EXPECTED_REFRESH["history"]:
            stale.append({"source": key, "last_success": source.get("last_success")})
    summary_stamp = _parse_time(summary.get("generated"))
    if summary_stamp and now - summary_stamp > EXPECTED_REFRESH["current"]:
        stale.append({"source": "current", "last_success": summary.get("generated")})
    checks.append(
        _check(
            "data-freshness",
            "Published data is not older than its expected refresh interval.",
            "flag" if stale else "pass",
            {"stale_sources": stale, "expected_intervals": {"current": "3 hours", "history": "8 days"}},
            [WFIGS_QUERY_URL],
        )
    )

    counts = {status: sum(check["status"] == status for check in checks) for status in ("pass", "flag", "fail")}
    return {
        "generated": now.isoformat(timespec="seconds"),
        "summary": counts,
        "checks": checks,
        "limitations": "These checks catch internal inconsistency and implausible values; they do not certify upstream sources or our interpretation.",
    }


def write_verification(data_dir=DATA_DIR, now=None):
    data_dir = pathlib.Path(data_dir)
    try:
        summary = json.loads((data_dir / "summary.json").read_text())
        longterm = json.loads((data_dir / "longterm.json").read_text())
        points = json.loads((data_dir / "fire_years.json").read_text())
        result = build_verification(summary, longterm, points, now)
    except Exception as exc:  # noqa: BLE001 - make inability visible to readers
        result = {
            "generated": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
            "summary": {"pass": 0, "flag": 0, "fail": 0},
            "checks": [],
            "error": str(exc),
            "limitations": "Verification could not run; no claims are made about the generated data.",
        }
    (data_dir / "verification.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    result = write_verification()
    print(json.dumps(result, indent=2))
