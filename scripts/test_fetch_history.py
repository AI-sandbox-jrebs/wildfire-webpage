import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fetch_history import (
    MTBS_WILDFIRE_ONLY,
    annotate_mtbs_provisional,
    build_derived,
    build_fire_years,
    parse_mtbs_points,
    parse_nifc_table,
    parse_usdm,
    refresh_source,
)

FIXTURES = Path(__file__).parent / "fixtures"


class HistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sample = (FIXTURES / "nifc_stats.sample.html").read_text()

    def test_nifc_sample_table_parses(self):
        records = parse_nifc_table(self.sample)
        self.assertEqual({key: records[0][key] for key in ("year", "fires", "acres")}, {"year": 1983, "fires": 18229, "acres": 1323666})
        self.assertEqual(records[-1]["year"], 2025)
        self.assertGreater(len(records), 40)

    def test_derived_stats_flag_early_counts(self):
        records = [
            {"year": 1983, "fires": 10, "acres": 1000},
            {"year": 1984, "fires": 20, "acres": 2000},
            {"year": 1985, "fires": 100, "acres": 10000},
            {"year": 2020, "fires": 100, "acres": 25000},
        ]
        derived = build_derived(records)
        self.assertEqual(derived["decades"][0]["fire_years_used"], [1985])
        self.assertEqual(derived["top_10_after_2000"], 1)
        self.assertEqual(derived["recent_size_multiplier"], 2.5)
        self.assertTrue(derived["year_lookup"]["1983"]["count_flag"])
        self.assertEqual(derived["early_count_label"], "1985–1985")
        self.assertEqual(derived["recent_count_label"], "2020–2020")
        self.assertEqual(derived["top_10_sentence"], "1 of the ten biggest fire-years came since 2005")
        self.assertIn("acres", derived["takeaways"]["fire_size"]["sentence"])
        self.assertEqual(derived["takeaways"]["fire_counts"]["classification"], "natural variability")

    def test_failed_source_keeps_previous_good_series(self):
        previous = {
            "series": {
                "nifc": {
                    "records": [{"year": 2025, "fires": 1, "acres": 2}],
                    "metadata": {"last_success": "2026-01-01T00:00:00+00:00"},
                }
            },
            "sources": {"nifc": {"last_success": "2026-01-01T00:00:00+00:00"}},
        }
        output = {"series": {}, "sources": {}}
        with patch("fetch_history.SOURCE_META", {"nifc": {"name": "NIFC"}}):
            success = refresh_source(output, previous, "nifc", lambda: (_ for _ in ()).throw(RuntimeError("offline")), "now")
        self.assertFalse(success)
        self.assertEqual(output["series"]["nifc"], previous["series"]["nifc"])
        self.assertEqual(output["sources"]["nifc"]["status"], "failed")
        self.assertEqual(output["sources"]["nifc"]["last_success"], "2026-01-01T00:00:00+00:00")

    def test_usdm_uses_only_cumulative_d1_rows(self):
        weekly = []
        for year in range(2000, 2020):
            d1, d2, d3, d4 = year - 1990, 8, 4, 1
            for week in range(260):
                level = ("D1", d1), ("D2", d2), ("D3", d3), ("D4", d4)
                for name, value in level:
                    weekly.append({
                        "mapDate": f"{year}-01-{(week % 28) + 1:02d}",
                        "areaCurrentPercent": value,
                        "usdmLevel": name,
                    })
        records = parse_usdm(weekly)
        self.assertEqual(records[0], {"year": 2000, "value": 10.0})
        self.assertEqual(records[-1], {"year": 2019, "value": 29.0})

    def test_mtbs_points_filter_compaction_and_names(self):
        payload = {
            "features": [
                {"attributes": {
                    "fire_type": "Prescribed Fire", "year": 2020, "acres": 20000,
                    "latitude": 40.12345, "longitude": -120.98765, "fire_name": "RX",
                }},
                {"attributes": {
                    "fire_type": "Wildfire", "year": 2020, "acres": 12000,
                    "latitude": 40.12345, "longitude": -120.98765, "ig_date": 20200701,
                    "fire_name": "BIG FIRE",
                }},
                {"attributes": {
                    "fire_type": "Wildfire", "year": 2021, "acres": 9999,
                    "latitude": 41.98765, "longitude": -121.12345, "ig_date": 20210701,
                    "fire_name": "SMALL FIRE",
                }},
            ]
        }
        points = parse_mtbs_points(payload, 2025)
        self.assertEqual(len(points), 2)
        self.assertEqual(points[0]["lat"], 40.123)
        self.assertEqual(points[0]["acres"], 12000)
        self.assertEqual(points[0]["name"], "BIG FIRE")
        self.assertNotIn("name", points[1])
        self.assertIn("Wildfire", MTBS_WILDFIRE_ONLY)

    def test_mtbs_provisional_ratio(self):
        output = {
            "series": {
                "nifc": {"records": [
                    {"year": 1997, "acres": 1000},
                    {"year": 2024, "acres": 1000},
                    {"year": 2025, "acres": 1000},
                ]},
                "mtbs": {"records": [
                    {"year": 1997, "acres": 100},
                    {"year": 2024, "acres": 700},
                    {"year": 2025, "acres": 100},
                ]},
            },
            "sources": {},
        }
        self.assertEqual(annotate_mtbs_provisional(output), [2025])
        self.assertFalse(output["series"]["mtbs"]["records"][0]["provisional"])
        self.assertFalse(output["series"]["mtbs"]["records"][1]["provisional"])
        self.assertTrue(output["series"]["mtbs"]["records"][2]["provisional"])

    def test_fire_years_shape_and_takeaways(self):
        points = [
            {"year": 2020, "lat": 40.123, "lon": -120.987, "acres": 12000, "name": "BIG"},
            {"year": 2020, "lat": 41.0, "lon": -121.0, "acres": 9},
        ]
        result = build_fire_years(points, {"last_success": "now"}, [2020])
        self.assertEqual(result["provisional_years"], [2020])
        self.assertEqual(result["years"]["2020"][0]["name"], "BIG")
        self.assertNotIn("year", result["years"]["2020"][0])


if __name__ == "__main__":
    unittest.main()
