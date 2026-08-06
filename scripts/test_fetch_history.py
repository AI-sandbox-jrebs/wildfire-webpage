import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fetch_history import build_derived, parse_nifc_table, parse_usdm, refresh_source


class HistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sample = Path("/home/ubuntu/histdata/nifc_stats_html.sample.html").read_text()

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


if __name__ == "__main__":
    unittest.main()
