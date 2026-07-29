# Wildfire &amp; Rainfall Watch

A static GitHub Pages site showing active wildfires with a live rainfall radar
overlay and per-fire precipitation history.

![screenshot](docs/screenshot.png)

## Data

| Layer | Source | Refreshed |
| --- | --- | --- |
| US incidents (>=100 acres) | [NIFC WFIGS](https://data-nifc.opendata.arcgis.com/) | at build time |
| Global wildfire events | [NASA EONET](https://eonet.gsfc.nasa.gov/) | at build time |
| Precipitation, past 7 d + 3 d forecast | [Open-Meteo](https://open-meteo.com/) | at build time |
| Rainfall radar tiles (last 2 h, animated) | [RainViewer](https://www.rainviewer.com/) | live in the browser |

No API keys are required.

## Rebuild

```bash
./scripts/rebuild.sh            # refresh data/fires.geojson + data/summary.json
COMMIT_DATA=1 ./scripts/rebuild.sh   # also commit the refreshed snapshot
python3 -m http.server 8000     # preview at http://localhost:8000
```

## Git hook

Enable the bundled hooks once per clone:

```bash
git config core.hooksPath .githooks
```

- `pre-push` refreshes and commits the data snapshot before each push.
- `post-merge` refreshes the local snapshot after each pull.

Set `SKIP_DATA_REFRESH=1` to bypass either hook.

## Deployment

`.github/workflows/deploy.yml` refreshes the data and publishes to GitHub Pages
on every push to `main`, every 3 hours on a schedule, and on manual dispatch.
Enable it under **Settings → Pages → Source: GitHub Actions**.
