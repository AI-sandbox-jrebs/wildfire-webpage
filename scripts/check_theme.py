"""Static checks for component-level theme literals."""

import pathlib
import re


CSS_PATH = pathlib.Path(__file__).resolve().parent.parent / "styles.css"
CHECKED_PROPERTIES = {"color", "background", "background-color"}
LITERAL = re.compile(r"(#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)|\b\d+(?:\.\d+)?px\b)")
THEME_COMPONENTS = (
    ".app-bar", ".view-nav", ".eyebrow", ".updates-view", ".verification-",
    ".update-card", ".update-kind", ".panel", ".tabs", ".chips", ".toggle",
    ".history-view", ".history-map-section", ".history-map-framing",
    ".history-year", ".history-chart", ".history-source",
)

# Map-specific ramps and chart geometry are intentionally literal. Their
# selectors are listed here so an exemption remains reviewable and localized.
ALLOWLIST = {
    ("#map", "background"): "map base surface",
    ("#history-map", "background"): "map fallback surface",
    ('body[data-view="then-vs-now"] .app-bar', "background"): "light editorial surface",
    ('body[data-view="then-vs-now"] .view-nav a', "color"): "light editorial surface",
    (".history-map-framing button[aria-pressed=\"true\"]", "background"): "light selected control",
    (".panel--list li:hover", "background"): "dark hover elevation",
}


def lint_stylesheet(path=CSS_PATH):
    lines = pathlib.Path(path).read_text().splitlines()
    violations = []
    selector = ""
    in_root = False
    for line_number, line in enumerate(lines, 1):
        stripped = line.strip()
        if "{" in stripped:
            selector = stripped.split("{", 1)[0].strip()
            in_root = selector == ":root"
        if in_root or not selector or "@" in selector:
            continue
        if not any(part in selector for part in THEME_COMPONENTS):
            continue
        body = stripped.split("{", 1)[-1].split("}", 1)[0]
        for declaration in body.split(";"):
            if ":" not in declaration:
                continue
            prop, value = (part.strip() for part in declaration.split(":", 1))
            if prop not in CHECKED_PROPERTIES or "var(" in value:
                continue
            if value in ("0", "none", "transparent", "inherit", "initial", "unset"):
                continue
            if (selector, prop) in ALLOWLIST:
                continue
            if LITERAL.search(value):
                violations.append({
                    "line": line_number,
                    "selector": selector,
                    "property": prop,
                    "value": value,
                })
    return violations


if __name__ == "__main__":
    problems = lint_stylesheet()
    if problems:
        for problem in problems:
            print(
                f"{problem['line']}: {problem['selector']} "
                f"{problem['property']}: {problem['value']}"
            )
        raise SystemExit(1)
    print("theme token lint: pass")
