import unittest
from datetime import datetime, timezone

from verify_data import build_verification


def fixture(mtbs_acres=80):
    metadata = {
        "url": "https://example.test/query?where=fire_type%3D%27Wildfire%27",
        "last_success": "2026-08-06T00:00:00+00:00",
    }
    return (
        {
            "generated": "2026-08-06T00:00:00+00:00",
            "fire_count": 2,
            "wfigs_reported_count": 2,
            "wfigs_count_check": {"source_total": 2, "fetched_count": 2, "status": "pass"},
            "total_acres": 200,
        },
        {
            "sources": {
                "nifc": {"last_success": metadata["last_success"], "metadata": {**metadata, "url": "https://example.test/nifc"}},
                "mtbs": {"last_success": metadata["last_success"], "metadata": metadata},
                "usdm": {"last_success": metadata["last_success"], "metadata": metadata},
            },
            "series": {
                "nifc": {"metadata": {**metadata, "url": "https://example.test/nifc"}, "records": [
                    {"year": 2024, "fires": 2, "acres": 100},
                    {"year": 2025, "fires": 2, "acres": 100},
                ]},
                "mtbs": {"metadata": metadata, "records": [
                    {"year": 2024, "acres": mtbs_acres, "provisional": False},
                    {"year": 2025, "acres": mtbs_acres, "provisional": True},
                ]},
                "usdm": {"metadata": metadata, "records": [
                    {"year": 2024, "value": 20},
                    {"year": 2025, "value": 30},
                ]},
            },
        },
        {
            "metadata": metadata,
            "provisional_years": [2025],
            "years": {"2024": [], "2025": []},
        },
    )


class VerificationTests(unittest.TestCase):
    def test_excess_threshold_violation_is_reported_as_failed(self):
        summary, longterm, points = fixture(mtbs_acres=125)
        result = build_verification(summary, longterm, points, datetime(2026, 8, 6, tzinfo=timezone.utc))
        check = next(item for item in result["checks"] if item["id"] == "mtbs-excess-calibration")
        self.assertEqual(check["status"], "fail")
        self.assertEqual(check["actual"]["extreme_years"][0]["year"], 2024)

    def test_checks_include_rerunnable_urls_and_pass_valid_fixture(self):
        summary, longterm, points = fixture()
        result = build_verification(summary, longterm, points, datetime(2026, 8, 6, tzinfo=timezone.utc))
        self.assertEqual(result["summary"]["fail"], 0)
        self.assertEqual(result["summary"]["flag"], 0)
        check = next(item for item in result["checks"] if item["id"] == "mtbs-excess-calibration")
        self.assertEqual(len(check["sources"]), 2)
        self.assertTrue(all(url for url in check["sources"]))

    def test_modest_excess_is_accepted(self):
        summary, longterm, points = fixture(mtbs_acres=111)
        result = build_verification(summary, longterm, points, datetime(2026, 8, 6, tzinfo=timezone.utc))
        check = next(item for item in result["checks"] if item["id"] == "mtbs-excess-calibration")
        self.assertEqual(check["status"], "pass")

    def test_current_count_without_build_attestation_is_flagged(self):
        summary, longterm, points = fixture()
        summary.pop("wfigs_count_check")
        result = build_verification(summary, longterm, points, datetime(2026, 8, 6, tzinfo=timezone.utc))
        check = next(item for item in result["checks"] if item["id"] == "current-fire-count")
        self.assertEqual(check["status"], "flag")

    def test_out_of_range_drought_is_reported(self):
        summary, longterm, points = fixture()
        longterm["series"]["usdm"]["records"][1]["value"] = 101
        result = build_verification(summary, longterm, points, datetime(2026, 8, 6, tzinfo=timezone.utc))
        check = next(item for item in result["checks"] if item["id"] == "drought-range")
        self.assertEqual(check["status"], "fail")

    def test_missing_wildfire_filter_is_reported(self):
        summary, longterm, points = fixture()
        longterm["series"]["mtbs"]["metadata"]["url"] = "https://example.test/mtbs"
        result = build_verification(summary, longterm, points, datetime(2026, 8, 6, tzinfo=timezone.utc))
        check = next(item for item in result["checks"] if item["id"] == "mtbs-wildfire-only")
        self.assertEqual(check["status"], "fail")

    def test_coverage_gap_is_reported(self):
        summary, longterm, points = fixture()
        longterm["series"]["nifc"]["records"].append({"year": 2027, "fires": 2, "acres": 100})
        result = build_verification(summary, longterm, points, datetime(2026, 8, 6, tzinfo=timezone.utc))
        check = next(item for item in result["checks"] if item["id"] == "coverage-nifc")
        self.assertEqual(check["status"], "fail")

    def test_missing_provenance_is_reported(self):
        summary, longterm, points = fixture()
        longterm["sources"]["mtbs"]["metadata"].pop("url")
        result = build_verification(summary, longterm, points, datetime(2026, 8, 6, tzinfo=timezone.utc))
        check = next(item for item in result["checks"] if item["id"] == "source-provenance")
        self.assertEqual(check["status"], "fail")

    def test_stale_data_is_flagged(self):
        summary, longterm, points = fixture()
        summary["generated"] = "2026-08-01T00:00:00+00:00"
        result = build_verification(summary, longterm, points, datetime(2026, 8, 6, tzinfo=timezone.utc))
        check = next(item for item in result["checks"] if item["id"] == "data-freshness")
        self.assertEqual(check["status"], "flag")


if __name__ == "__main__":
    unittest.main()
