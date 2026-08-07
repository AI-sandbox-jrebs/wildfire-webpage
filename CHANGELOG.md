# Updates

Public record of changes to Wildfire & Rainfall Watch.

## Fixed mobile history framing and sheet dismissal

**2026-08-07 · correction**

An iPhone report uncovered several mobile presentation and interaction defects in the history and Now views; the affected layouts and controls now behave as intended.

What changed:
- The historical map's mobile mis-framing had two independent causes: a mobile CSS offset intended only for the full-screen Now map was lifting the history attribution into the tiles, and the history map could fit before layout settled while Leaflet's default integer zoom snapping rejected the fractional zoom needed by a narrow phone container.
- Stats, Layers, and Fires sheets now have explicit close buttons, their opening chips toggle them closed, and closing a sheet returns focus to the chip so the map is unobstructed and keyboard users have a clear path out.
- The Then vs Now tab now uses a common history glyph instead of the U+25CC dotted-circle placeholder, which rendered poorly at tab size on iOS.

> Note: This correction was reported from an iPhone. The theme checks continued to pass because they compare computed geometry and typography across views; these defects were not in that check's scope.

---

## Added automated cross-view theme checks

**2026-08-06 · improvement**

The build review now includes a Chromium computed-style assertion so typography and component geometry cannot silently drift between views.

What changed:
- The browser check compares headings, eyebrows, cards, and controls across Updates and Then vs Now.
- Only explicitly named surface-brightness properties may differ; radius, borders, padding, and typography must match.
- A stylesheet token lint separately reports hardcoded component colours with selectors and line numbers.

> Note: The browser assertion is run with python3 scripts/check_theme_browser.py.

---

## Aligned the visual language across all views

**2026-08-06 · improvement**

Now, Updates, and Then vs Now now share the same type hierarchy, card treatment, controls, focus rings, and semantic colour meanings while keeping their distinct dark and light surfaces.

What changed:
- Added a stylesheet token check for hardcoded component colours and a browser review of shared computed styles.
- Fixed older Now and Updates controls, headings, cards, and status treatments that had drifted from the historical editorial view.
- Play years now restarts from the first year when pressed at the end of the scrubber.

> Note: Surface brightness remains the only intentional cross-view styling difference.

---

## Published machine-checkable data verification

**2026-08-06 · improvement**

The Updates view now shows the checks we run over the generated data, the values compared, and links to the source queries a reader can rerun.

What changed:
- Checks cover cross-source acreage comparisons, wildfire-only MTBS filtering, provisional-year recency, current-fire counts, drought ranges, coverage gaps, plausible values, provenance, and freshness.
- The results are diagnostic rather than a certification: they can catch internal inconsistency and malformed values, but they cannot prove that an upstream source or our interpretation is correct.
- This site is AI-built and its corrections are logged publicly, including the stale EONET records, prescribed-fire contamination, and MTBS assessment-lag fixes.

> Note: A failed or flagged check is shown rather than hidden; source links point to the query or data endpoint used for the comparison.

---

## Calibrated the MTBS cross-source verification check

**2026-08-06 · correction**

The MTBS/NIFC comparison now allows modest measurement differences while still detecting the larger and repeated excess pattern caused by the former all-fire-types query.

What changed:
- MTBS maps perimeter footprints, which can include unburned inclusions, while NIFC reports incident acreage; the products are not strict subsets.
- The check now flags unusually large single-year excess or excess across too many years. The wildfire-only generated history passes this calibrated check, while the former all-fire-types result would have failed it.

> Note: The source-method caveat is part of the check description shown on Updates.

---

## Removed prescribed burns from the mapped burned-area history

**2026-08-06 · correction**

Our MTBS burned-area chart was counting deliberately-set prescribed burns as wildfires. This is the same mistake we had just corrected in the current-fire totals, made one layer down in the historical data.

**Before:** 2020: 10.30M acres mapped (all fire types, no completeness flag)
**After:** 2020: 9.65M acres mapped (wildfires only); 2025 flagged provisional

What changed:
- MTBS maps four kinds of fire: wildfires, prescribed fires, wildland fire use, and other. We were summing all of them. Of the 30,908 events we were including, 9,638 were prescribed burns contributing 18,187,450 acres, and only 16,756 were wildfires.
- Every MTBS query is now restricted to wildfires, and a test guards against the filter being dropped again.
- Separately, the newest years in this series were understated in a way that read like a collapse in burning. MTBS assesses fires a season or more after they burn, so 2025 has only 51 fires mapped so far, covering 22% of the acreage NIFC reported. Recent years that are still filling in are now flagged as provisional, drawn differently, and excluded from year-to-year comparisons.
- The provisional flag deliberately applies only to recent years. Older years also map a smaller share of NIFC's total, but that is because MTBS only maps fires above a size threshold, not because the data is incomplete, so labelling them unfinished would have been wrong.

> Note: MTBS remains a separate mapped product with its own size and selection criteria. It is never added to or substituted for the NIFC all-wildland-fire totals.

[Inspect pull request #7](https://github.com/AI-sandbox-jrebs/wildfire-webpage/pull/7)

---

## Added a geographic Then vs Now map

**2026-08-06 · feature**

The history view now shows where mapped wildfires happened year by year, alongside the charts that explain how the pattern changed.

What changed:
- A shared year scrubber updates the historical map and the figures together, while Play years lets you watch the record advance.
- Historical burns use charcoal tones rather than the ember colours reserved for active fires, and provisional MTBS years are marked while assessments catch up.
- The navigation now stays visible as a clear desktop app bar or a thumb-friendly mobile tab bar.

> Note: The map uses MTBS wildfire centroids, not fire perimeters, and keeps provisional recent years separate from completed-year comparisons.

[Inspect pull request #7](https://github.com/AI-sandbox-jrebs/wildfire-webpage/pull/7)

---

## Added a Then vs Now view for historical context

**2026-08-06 · feature**

The live fire map shows what is happening now. This view helps put that danger in context by showing whether today's pattern is genuinely different from the past.

What changed:
- Fire counts are not rising compared with the 1990s, but the average fire is now about two and a half times larger than in the late 1980s.
- Every one of the ten largest fire-years in the national record happened after 2000.
- A year scrubber lets you inspect fires, acres, average fire size, rainfall, temperature, and drought together, with the source limits shown alongside the charts.

> Note: The national fire-count record has incomplete reporting in 1983–84, so those years are flagged rather than treated as a clean baseline.

---

## Removed stale and prescribed-fire records from the fire totals

**2026-08-06 · correction**

The headline was overstating current fire activity by about a third. Roughly 35% of the acreage we reported as burning came from a feed that never closed out old fires and did not distinguish wildfires from deliberate controlled burns. That data is gone.

**Before:** 677 fires · 5.27M acres
**After:** 296 fires · 3.41M acres

What changed:
- We combined two sources: NIFC WFIGS and NASA EONET. On audit, EONET turned out to be a stale mirror of the same underlying government system WFIGS reads from, but it never marks events as finished. Of the 441 EONET fires we were plotting as actively burning, WFIGS still listed exactly 1 as a current incident. The median fire among them had been discovered 115 days earlier.
- 44% of those EONET records (194 fires, 250,746 acres) were prescribed burns: intentional, planned, managed fires. WFIGS labels and excludes these; EONET publishes no field that identifies them, so they were being counted as wildfires.
- EONET was originally added for coverage outside the US, but none of its events were outside the US, so it was not doing that job either.
- To keep good coverage without padding the count, we lowered the minimum fire size we display from 100 acres to 10 acres. This adds smaller real wildfires from the authoritative source.

> Note: Fewer fires are shown now than before. That is the correction working: the map had been counting months-old and intentionally-set fires as currently burning.

[Inspect pull request #3](https://github.com/AI-sandbox-jrebs/wildfire-webpage/pull/3)

---

## Rain radar now refreshes while panning and animates on its own

**2026-07-31 · fix**

If you turned off the fire and smoke layers and left only the rainfall radar on, panning the map left stale radar behind, and the animation would sometimes not run at all.

What changed:
- The radar layer was waiting for the map to come to a complete stop before loading new tiles, so dragging across the map showed empty or outdated radar. It now refreshes as you pan on desktop, while keeping the stricter, memory-saving behaviour on phones.
- Starting and stopping the animation was tied to the wrong control, so whether the loop ran depended on the order you had clicked the checkboxes. Showing or hiding the radar now directly starts and stops the animation.

[Inspect pull request #2](https://github.com/AI-sandbox-jrebs/wildfire-webpage/pull/2)

---

## Smoke plumes, air quality, and fire growth tracking

**2026-07-31 · feature**

Added the context needed to answer "is this getting worse, and does it reach me?" — smoke coverage, air quality near fires, and how fast each fire is actually growing.

What changed:
- NOAA satellite smoke plumes (light, medium, heavy) as a toggleable layer, plus an estimate of how many people are under a plume.
- US Air Quality Index near large fires, coloured by the official EPA bands.
- Per-fire growth: acres gained, containment change, and an acreage-over-time chart, plus a "fastest growing" list alongside "largest".
- Growth is only ever shown when we can compare against a real measurement 18 to 36 hours old. We never estimate, interpolate, or fill in growth numbers — if there is no qualifying earlier measurement, the page says so instead of guessing.

> Note: The people-under-smoke figure counts city centres inside a plume and is deliberately reported as a floor, not a total exposure count.

[Inspect pull request #1](https://github.com/AI-sandbox-jrebs/wildfire-webpage/pull/1)

---

## Fixed an iPhone Safari crash when pinch-zooming

**2026-07-29 · fix**

Zooming hard on an iPhone could kill the page with "a problem repeatedly occurred".

What changed:
- The animated radar was being drawn as twelve separate stacked map layers, each holding its own set of image tiles in memory at once. Pinch-zooming multiplied that until Safari ran out of memory and killed the tab.
- It is now a single radar layer that swaps its image source per frame, so memory stays flat no matter how far you zoom. Also reduced how many tiles phones hold onto, capped the radar's detail level, and added error handling so an unexpected failure shows a small notice instead of a blank page.

---

## Smoother panning and zooming, and a real mobile layout

**2026-07-29 · improvement**

Panning and zooming were stuttering, and the desktop layout was being squeezed onto phones.

What changed:
- Map tiles are now pre-loaded in a ring around whatever you are looking at, so panning reveals map instead of blank squares.
- Fire markers are drawn onto a single canvas rather than as hundreds of individual page elements, which was the main source of stutter.
- Phones get their own layout: a full-screen map with Stats, Layers, and Top Fires as bottom sheets.

---

## First release

**2026-07-29 · feature**

A map of active US wildfires with a live animated rainfall radar overlay, rebuilt automatically several times a day.

What changed:
- Active fire locations and sizes from NIFC, with recent and forecast rainfall for each of the largest fires.
- Live animated precipitation radar from RainViewer.
- The site rebuilds itself from the source feeds on a schedule, so what you see reflects the latest published data rather than a hand-updated snapshot.

---
