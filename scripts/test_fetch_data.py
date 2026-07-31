"""Tests for the derived numbers shown on the page.

Growth and smoke-impact figures are the two places where we compute rather than
relay, so they are the two places a bug would quietly mislead people.
"""

import unittest
from datetime import datetime, timedelta, timezone

import fetch_data as fd


def iso(dt):
    return dt.isoformat(timespec="seconds")


NOW = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)


class DeriveGrowthTests(unittest.TestCase):
    def test_no_growth_without_a_baseline_in_window(self):
        points = [[iso(NOW - timedelta(hours=3)), 100, 0], [iso(NOW), 400, 0]]
        self.assertIsNone(fd.derive_growth(points, {"acres": 400}, NOW))

    def test_no_growth_from_a_single_point(self):
        points = [[iso(NOW), 400, 0]]
        self.assertIsNone(fd.derive_growth(points, {"acres": 400}, NOW))

    def test_growth_against_a_real_24h_snapshot(self):
        points = [
            [iso(NOW - timedelta(hours=24)), 1000, 10],
            [iso(NOW - timedelta(hours=3)), 1200, 20],
            [iso(NOW), 1500, 25],
        ]
        growth = fd.derive_growth(points, {"acres": 1500, "contained": 25}, NOW)
        self.assertEqual(growth["acres_delta"], 500)
        self.assertEqual(growth["pct"], 50.0)
        self.assertEqual(growth["contained_delta"], 15)
        self.assertEqual(growth["hours"], 24.0)

    def test_baseline_older_than_window_is_rejected(self):
        points = [[iso(NOW - timedelta(days=5)), 10, 0], [iso(NOW), 900, 0]]
        self.assertIsNone(fd.derive_growth(points, {"acres": 900}, NOW))

    def test_shrinking_acreage_is_reported_as_negative(self):
        points = [[iso(NOW - timedelta(hours=24)), 1000, 0], [iso(NOW), 900, 0]]
        growth = fd.derive_growth(points, {"acres": 900}, NOW)
        self.assertEqual(growth["acres_delta"], -100)


class BurnRateTests(unittest.TestCase):
    def test_average_since_discovery(self):
        props = {"acres": 1000, "discovered": iso(NOW - timedelta(days=10))}
        self.assertEqual(fd.average_burn_rate(props, NOW), 100.0)

    def test_none_for_fires_younger_than_a_day(self):
        props = {"acres": 1000, "discovered": iso(NOW - timedelta(hours=6))}
        self.assertIsNone(fd.average_burn_rate(props, NOW))

    def test_none_without_a_discovery_date(self):
        self.assertIsNone(fd.average_burn_rate({"acres": 1000, "discovered": None}, NOW))


def square(min_lon, min_lat, max_lon, max_lat):
    return [
        [min_lon, min_lat],
        [max_lon, min_lat],
        [max_lon, max_lat],
        [min_lon, max_lat],
        [min_lon, min_lat],
    ]


class SmokeImpactTests(unittest.TestCase):
    def plume(self, density, ring, holes=()):
        return {
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [ring, *holes]},
            "properties": {"density": density},
        }

    def test_counts_only_cities_inside_a_plume(self):
        smoke = {
            "analysis_date": "2026-07-30",
            "features": [self.plume("Light", square(-10, -10, 10, 10))],
        }
        cities = [
            {"n": "Inside", "s": "XX", "lat": 0, "lon": 0, "p": 100},
            {"n": "Outside", "s": "XX", "lat": 50, "lon": 50, "p": 900},
        ]
        impact = fd.smoke_impact(smoke, cities)
        self.assertEqual(impact["city_count"], 1)
        self.assertEqual(impact["population"], 100)

    def test_city_counted_once_at_its_worst_density(self):
        smoke = {
            "features": [
                self.plume("Light", square(-10, -10, 10, 10)),
                self.plume("Heavy", square(-5, -5, 5, 5)),
            ]
        }
        cities = [{"n": "Overlap", "s": "XX", "lat": 0, "lon": 0, "p": 100}]
        impact = fd.smoke_impact(smoke, cities)
        self.assertEqual(impact["city_count"], 1)
        self.assertEqual(impact["population"], 100)
        self.assertEqual(impact["cities_by_density"], {"Light": 0, "Medium": 0, "Heavy": 1})

    def test_holes_are_not_covered(self):
        smoke = {
            "features": [
                self.plume("Medium", square(-10, -10, 10, 10), holes=[square(-5, -5, 5, 5)])
            ]
        }
        cities = [
            {"n": "InHole", "s": "XX", "lat": 0, "lon": 0, "p": 100},
            {"n": "InRing", "s": "XX", "lat": 7, "lon": 7, "p": 200},
        ]
        impact = fd.smoke_impact(smoke, cities)
        self.assertEqual(impact["city_count"], 1)
        self.assertEqual(impact["population"], 200)


if __name__ == "__main__":
    unittest.main()
