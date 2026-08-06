# Updates

Public record of changes to Wildfire & Rainfall Watch.

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
