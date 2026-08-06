"""Validate data/changelog.json and render the public Markdown changelog."""

import json
import sys
from datetime import date
from pathlib import Path


KINDS = {"correction", "fix", "feature", "improvement"}
REQUIRED_FIELDS = {"date", "kind", "title", "summary", "details"}


def validate_entries(entries):
    if not isinstance(entries, list):
        raise ValueError("changelog must be a JSON array")

    previous = None
    for index, entry in enumerate(entries, 1):
        if not isinstance(entry, dict):
            raise ValueError(f"entry {index} must be an object")
        missing = REQUIRED_FIELDS - entry.keys()
        if missing:
            raise ValueError(f"entry {index} missing required fields: {', '.join(sorted(missing))}")
        try:
            current = date.fromisoformat(entry["date"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"entry {index} has invalid date: {entry.get('date')!r}") from exc
        if previous and current > previous:
            raise ValueError("changelog dates must be in descending order")
        previous = current
        if entry["kind"] not in KINDS:
            raise ValueError(f"entry {index} has invalid kind: {entry['kind']!r}")
        for field in ("title", "summary"):
            if not isinstance(entry[field], str) or not entry[field].strip():
                raise ValueError(f"entry {index} field {field!r} must be a non-empty string")
        if not isinstance(entry["details"], list) or not all(
            isinstance(detail, str) and detail.strip() for detail in entry["details"]
        ):
            raise ValueError(f"entry {index} details must be a list of non-empty strings")
        if "note" in entry and not isinstance(entry["note"], str):
            raise ValueError(f"entry {index} note must be a string")
        if "pr" in entry and (
            isinstance(entry["pr"], bool) or not isinstance(entry["pr"], int) or entry["pr"] <= 0
        ):
            raise ValueError(f"entry {index} pr must be a positive integer")
        impact = entry.get("impact")
        if impact is not None:
            if not isinstance(impact, dict) or not {"before", "after"} <= impact.keys():
                raise ValueError(f"entry {index} impact must contain before and after")
            if not all(isinstance(impact[field], str) for field in ("before", "after")):
                raise ValueError(f"entry {index} impact values must be strings")
    return entries


def load_entries(source):
    try:
        entries = json.loads(Path(source).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read changelog JSON: {exc}") from exc
    return validate_entries(entries)


def markdown(entries):
    lines = ["# Updates", "", "Public record of changes to Wildfire & Rainfall Watch.", ""]
    for entry in entries:
        lines.extend(
            [
                f"## {entry['title']}",
                "",
                f"**{entry['date']} · {entry['kind']}**",
                "",
                entry["summary"],
                "",
            ]
        )
        if entry.get("impact"):
            lines.extend(
                [
                    f"**Before:** {entry['impact']['before']}",
                    f"**After:** {entry['impact']['after']}",
                    "",
                ]
            )
        lines.append("What changed:")
        lines.extend(f"- {detail}" for detail in entry["details"])
        if entry.get("note"):
            lines.extend(["", f"> Note: {entry['note']}"])
        if entry.get("pr"):
            lines.extend(
                [
                    "",
                    f"[Inspect pull request #{entry['pr']}](https://github.com/AI-sandbox-jrebs/wildfire-webpage/pull/{entry['pr']})",
                ]
            )
        lines.extend(["", "---", ""])
    return "\n".join(lines).rstrip() + "\n"


def generate_changelog(source, destination):
    entries = load_entries(source)
    Path(destination).write_text(markdown(entries))
    return entries


def main():
    root = Path(__file__).resolve().parent.parent
    try:
        generate_changelog(root / "data/changelog.json", root / "CHANGELOG.md")
    except ValueError as exc:
        print(f"changelog validation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
