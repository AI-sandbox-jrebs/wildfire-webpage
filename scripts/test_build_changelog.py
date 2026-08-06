import json
import tempfile
import unittest
from pathlib import Path

from build_changelog import generate_changelog, validate_entries


class ChangelogValidationTests(unittest.TestCase):
    def test_valid_entries_generate_markdown(self):
        entries = [
            {
                "date": "2026-08-06",
                "kind": "correction",
                "title": "A correction",
                "summary": "A summary.",
                "details": ["A detail."],
                "impact": {"before": "old", "after": "new"},
                "pr": 3,
            }
        ]
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "changelog.json"
            destination = Path(directory) / "CHANGELOG.md"
            source.write_text(json.dumps(entries))
            generate_changelog(source, destination)
            output = destination.read_text()
        self.assertIn("A correction", output)
        self.assertIn("**Before:** old", output)
        self.assertIn("pull request #3", output)

    def test_invalid_kind_and_order_are_rejected(self):
        base = {
            "date": "2026-08-06",
            "kind": "correction",
            "title": "Title",
            "summary": "Summary",
            "details": ["Detail"],
        }
        with self.assertRaisesRegex(ValueError, "invalid kind"):
            validate_entries([{**base, "kind": "oops"}])
        with self.assertRaisesRegex(ValueError, "descending order"):
            validate_entries([base, {**base, "date": "2026-08-07"}])


if __name__ == "__main__":
    unittest.main()
