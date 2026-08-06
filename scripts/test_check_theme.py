import tempfile
import unittest
from pathlib import Path

from check_theme import lint_stylesheet


class ThemeLintTests(unittest.TestCase):
    def test_stylesheet_passes(self):
        self.assertEqual(lint_stylesheet(), [])

    def test_hardcoded_component_color_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "styles.css"
            path.write_text(".update-card { color: #ffffff; }\n")
            violations = lint_stylesheet(path)
        self.assertEqual(violations[0]["line"], 1)
        self.assertEqual(violations[0]["selector"], ".update-card")


if __name__ == "__main__":
    unittest.main()
