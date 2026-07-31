/* Wildfire + rainfall map. Data is baked into data/ at build time; the rain
   radar is fetched live from RainViewer at page load. */

const RAINVIEWER_INDEX = "https://api.rainviewer.com/public/weather-maps.json";
const ANIMATION_MS = 700;

/* iOS Safari (WebKit) is the memory-tightest target: cap tile prefetch and
   radar history so pinch-zoom can't blow the tab's memory budget. */
const IS_TOUCH = window.matchMedia("(pointer: coarse)").matches;
const MAX_ZOOM = 18;

/* Never let a stray runtime error blank the whole page — surface it, keep the
   map alive. */
function showBanner(msg) {
  let el = document.getElementById("error-banner");
  if (!el) {
    el = document.createElement("div");
    el.id = "error-banner";
    el.className = "error-banner";
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(showBanner._t);
  showBanner._t = setTimeout(() => el.classList.remove("show"), 6000);
}
window.addEventListener("error", (e) => {
  console.error(e.error || e.message);
  showBanner("Something hiccuped — the map is still usable.");
});
window.addEventListener("unhandledrejection", (e) => {
  console.error("unhandled", e.reason);
});

const map = L.map("map", {
  center: [39.5, -108],
  zoom: 5,
  minZoom: 2,
  maxZoom: MAX_ZOOM,
  zoomControl: false,
  worldCopyJump: true,
  preferCanvas: true,
  zoomSnap: 0.5,
  zoomDelta: 0.5,
  wheelPxPerZoomLevel: 90,
  inertiaDeceleration: 2400,
  // WebKit chokes on very fast pinch bounce animations with many layers.
  bounceAtZoomLimits: false,
});

const TILE_OPTS = {
  keepBuffer: IS_TOUCH ? 2 : 4,
  updateWhenIdle: IS_TOUCH,
  updateWhenZooming: false,
  updateInterval: 120,
  crossOrigin: true,
  maxZoom: MAX_ZOOM,
};
L.control.zoom({ position: "bottomright" }).addTo(map);

L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
  attribution: '&copy; OpenStreetMap &copy; CARTO',
  ...TILE_OPTS,
}).addTo(map);
L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_only_labels/{z}/{x}/{y}{r}.png", {
  pane: "shadowPane",
  ...TILE_OPTS,
}).addTo(map);

const fireLayer = L.layerGroup().addTo(map);
const markersByKey = new Map();

// Smoke sits above the basemap but below fires and radar.
map.createPane("smoke");
map.getPane("smoke").style.zIndex = 350;
map.getPane("smoke").style.pointerEvents = "none";

const nf = new Intl.NumberFormat("en-US");
const fmtAcres = (a) => (a == null ? "unknown" : `${nf.format(Math.round(a))} ac`);
const fmtPeople = (n) =>
  n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${Math.round(n / 1e3)}k` : nf.format(n);
const fmtSigned = (n) => `${n > 0 ? "+" : ""}${nf.format(Math.round(n))}`;

function baseRadius(acres) {
  if (!acres) return 3;
  return Math.max(3, Math.min(22, 2.2 + Math.log10(acres) * 3.4));
}

/* Keep markers readable: tiny and non-overlapping when zoomed out, generous
   when zoomed in. */
function zoomFactor() {
  return Math.max(0.42, Math.min(1.9, 0.3 + map.getZoom() * 0.11));
}

function fireColor(acres) {
  if (!acres) return "#ff7b3d";
  if (acres >= 50000) return "#ffd166";
  if (acres >= 10000) return "#ff9e3d";
  return "#ff5f2e";
}

function sparkline(rain) {
  if (!rain || !rain.precip_mm.length) return "";
  const max = Math.max(...rain.precip_mm, 1);
  const bars = rain.precip_mm
    .map((mm, i) => {
      const future = i >= rain.precip_mm.length - 3;
      const h = Math.max(2, Math.round((mm / max) * 44));
      return `<i class="${future ? "future" : ""}" style="height:${h}px" title="${rain.days[i]}: ${mm} mm"></i>`;
    })
    .join("");
  return `<div class="spark">${bars}</div>
    <div class="spark-label"><span>7 days ago</span><span>+3 d forecast</span></div>`;
}

/* Air quality uses the official US AQI bands so the colour means the same thing
   it does on any government air-quality site. */
function aqiBand(aqi) {
  if (aqi <= 50) return { label: "Good", cls: "aqi--good" };
  if (aqi <= 100) return { label: "Moderate", cls: "aqi--mod" };
  if (aqi <= 150) return { label: "Unhealthy for sensitive groups", cls: "aqi--usg" };
  if (aqi <= 200) return { label: "Unhealthy", cls: "aqi--unhealthy" };
  if (aqi <= 300) return { label: "Very unhealthy", cls: "aqi--very" };
  return { label: "Hazardous", cls: "aqi--hazard" };
}

/* Acreage over time from our own recorded snapshots. Drawn as an area chart so
   a steep ramp reads as "this is running" at a glance on a phone. */
function growthChart(growth) {
  const series = (growth && growth.series) || [];
  if (series.length < 2) return "";
  const values = series.map((p) => p[1]);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const w = 240;
  const h = 54;
  const pts = series.map((p, i) => {
    const x = (i / (series.length - 1)) * w;
    const y = h - ((p[1] - min) / span) * (h - 6) - 3;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const first = new Date(series[0][0]).toLocaleDateString([], { month: "short", day: "numeric" });
  return `<div class="growth">
    <svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" role="img"
         aria-label="Acres over time, ${nf.format(min)} to ${nf.format(max)} acres">
      <polygon points="0,${h} ${pts.join(" ")} ${w},${h}" fill="rgba(255,120,60,0.22)" />
      <polyline points="${pts.join(" ")}" fill="none" stroke="#ff8a4c" stroke-width="2"
                stroke-linejoin="round" stroke-linecap="round" />
    </svg>
    <div class="spark-label"><span>${first}</span><span>now</span></div>
  </div>`;
}

function growthSummary(p) {
  if (p.growth) {
    const g = p.growth;
    const dir = g.acres_delta > 0 ? "grew" : g.acres_delta < 0 ? "revised down" : "held at";
    const pct = g.pct != null ? ` (${fmtSigned(g.pct)}%)` : "";
    return `<div class="growth-line ${g.acres_delta > 0 ? "up" : ""}">
      ${dir} <strong>${fmtSigned(g.acres_delta)} ac</strong>${pct} in the last ${Math.round(g.hours)} h</div>`;
  }
  if (p.burn_rate) {
    return `<div class="growth-line muted">averaging ${nf.format(Math.round(p.burn_rate))} ac/day since it started</div>`;
  }
  return "";
}

function popupHtml(p) {
  const rows = [
    ["Size", fmtAcres(p.acres)],
    ["Contained", p.contained == null ? "—" : `${Math.round(p.contained)}%`],
    ["Started", p.discovered ? new Date(p.discovered).toLocaleDateString() : "—"],
    ["Cause", p.cause || "—"],
  ];
  if (p.growth && p.growth.contained_delta) {
    rows.push(["Containment", `${fmtSigned(p.growth.contained_delta)} pts in ${Math.round(p.growth.hours)} h`]);
  }
  if (p.rain) {
    rows.push(["Rain, past 7 d", `${p.rain.past_7d_mm} mm`]);
    rows.push(["Rain, next 3 d", `${p.rain.next_3d_mm} mm`]);
  }
  let aqiHtml = "";
  if (p.aqi) {
    const band = aqiBand(p.aqi.us_aqi);
    aqiHtml = `<div class="aqi ${band.cls}">
      <span class="aqi__val">${p.aqi.us_aqi}</span>
      <span class="aqi__txt">US AQI nearby · ${band.label}</span></div>`;
  }
  return `<div class="pop">
    <h3>${p.name}</h3>
    <div class="where">${p.state ? p.state + " · " : ""}${p.source === "WFIGS" ? "NIFC incident" : "NASA EONET event"}</div>
    ${growthSummary(p)}
    ${growthChart(p.growth)}
    ${aqiHtml}
    <table>${rows.map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join("")}</table>
    ${sparkline(p.rain)}
  </div>`;
}

let allFeatures = [];
let listMode = "acres";

function renderList(features) {
  allFeatures = features;
  const list = document.getElementById("fire-list");
  const note = document.getElementById("list-note");
  const byGrowth = listMode === "growth";

  let top;
  if (byGrowth) {
    top = features
      .filter((f) => (f.properties.growth || {}).acres_delta > 0)
      .sort((a, b) => b.properties.growth.acres_delta - a.properties.growth.acres_delta)
      .slice(0, 25);
  } else {
    top = [...features]
      .filter((f) => f.properties.acres)
      .sort((a, b) => b.properties.acres - a.properties.acres)
      .slice(0, 25);
  }

  // Growth needs two snapshots a day apart, so it is empty on a fresh deploy.
  // Say so plainly rather than showing an unexplained blank list.
  if (byGrowth && !top.length) {
    note.hidden = false;
    note.textContent =
      "No measured growth yet. This compares each fire against a snapshot taken 24 h earlier, so it fills in once the site has been collecting for a day.";
  } else if (byGrowth) {
    note.hidden = false;
    note.textContent = "Change in reported acreage vs ~24 h ago.";
  } else {
    note.hidden = true;
  }

  list.innerHTML = top
    .map((f, i) => {
      const p = f.properties;
      const rain = p.rain ? `${p.rain.past_7d_mm} mm rain / 7 d` : "no rainfall sample";
      const wet = p.rain && p.rain.past_7d_mm >= 10 ? " wet" : "";
      const value = byGrowth ? fmtSigned(p.growth.acres_delta) : nf.format(Math.round(p.acres));
      const meta = byGrowth
        ? `${p.state || "intl"} · now ${nf.format(Math.round(p.acres))} ac`
        : `${p.state || "intl"} · ${rain}`;
      return `<li data-key="${featureKey(f)}" tabindex="0">
        <span class="name">${i + 1}. ${p.name}</span>
        <span class="acres${byGrowth ? " up" : ""}">${value}</span>
        <span class="meta${byGrowth ? "" : wet}">${meta}</span>
      </li>`;
    })
    .join("");
  list.querySelectorAll("li").forEach((li) => {
    const focus = () => {
      const marker = markersByKey.get(li.dataset.key);
      if (!marker) return;
      map.flyTo(marker.getLatLng(), Math.max(map.getZoom(), 8), { duration: 0.8 });
      marker.openPopup();
    };
    li.addEventListener("click", focus);
    li.addEventListener("keydown", (e) => e.key === "Enter" && focus());
  });
}

const featureKey = (f) => `${f.geometry.coordinates.join(",")}|${f.properties.name}`;

async function loadFires() {
  const res = await fetch(`data/fires.geojson?v=${Date.now()}`);
  const geo = await res.json();
  geo.features
    .sort((a, b) => (a.properties.acres || 0) - (b.properties.acres || 0))
    .forEach((f) => {
      const [lon, lat] = f.geometry.coordinates;
      const color = fireColor(f.properties.acres);
      const marker = L.circleMarker([lat, lon], {
        radius: baseRadius(f.properties.acres) * zoomFactor(),
        color,
        weight: 1,
        opacity: 0.9,
        fillColor: color,
        fillOpacity: 0.45,
        className: "fire-dot",
      }).bindPopup(popupHtml(f.properties), { closeButton: true });
      marker.baseRadius = baseRadius(f.properties.acres);
      marker.addTo(fireLayer);
      markersByKey.set(featureKey(f), marker);
    });
  renderList(geo.features);
  let raf = 0;
  map.on("zoomend", () => {
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(() => {
      const z = zoomFactor();
      markersByKey.forEach((m) => m.setRadius(m.baseRadius * z));
    });
  });
  return geo;
}

async function loadSummary() {
  const res = await fetch(`data/summary.json?v=${Date.now()}`);
  const s = await res.json();
  document.getElementById("stat-fires").textContent = nf.format(s.fire_count);
  document.getElementById("stat-acres").textContent =
    s.total_acres >= 1e6 ? `${(s.total_acres / 1e6).toFixed(1)}M` : nf.format(s.total_acres);
  document.getElementById("stat-dry").textContent = nf.format(s.dry_fire_count);
  document.getElementById("stat-updated").textContent = new Date(s.generated).toLocaleString();

  if (s.smoke && s.smoke.city_count) {
    const sm = s.smoke;
    document.getElementById("smoke-stat").hidden = false;
    document.getElementById("smoke-people").textContent = fmtPeople(sm.population);
    const age = sm.age_days > 0 ? ` (${sm.analysis_date} analysis)` : " (today's analysis)";
    document.getElementById("smoke-note").textContent =
      `${nf.format(sm.city_count)} towns and cities of 15k+ sit under a NOAA smoke plume${age}. ` +
      `Counts city centres, so it is a floor, not a total.`;
  }

  const gs = document.getElementById("growth-stat");
  if (s.growing_count) {
    gs.hidden = false;
    document.getElementById("growth-headline").textContent =
      `${fmtSigned(s.acres_gained_24h)} acres in 24 h`;
    document.getElementById("growth-note").textContent =
      `across ${nf.format(s.growing_count)} growing fires`;
  } else if (s.history_since) {
    gs.hidden = false;
    document.getElementById("growth-headline").textContent = "Growth tracking is warming up";
    document.getElementById("growth-note").textContent =
      `Recording since ${new Date(s.history_since).toLocaleDateString()}; 24 h comparisons appear once two snapshots exist.`;
  }
}

/* ---- smoke plumes (NOAA HMS, refreshed at build time) ---- */
const SMOKE_STYLE = {
  Light: { color: "#cfd8e3", fillOpacity: 0.1, weight: 0.5 },
  Medium: { color: "#e7d3a8", fillOpacity: 0.18, weight: 0.6 },
  Heavy: { color: "#e0a06a", fillOpacity: 0.3, weight: 0.8 },
};
let smokeLayer = null;

async function loadSmoke() {
  const res = await fetch(`data/smoke.geojson?v=${Date.now()}`);
  if (!res.ok) return;
  const geo = await res.json();
  if (!geo.features || !geo.features.length) return;
  smokeLayer = L.geoJSON(geo, {
    pane: "smoke",
    interactive: false,
    style: (f) => ({
      ...(SMOKE_STYLE[f.properties.density] || SMOKE_STYLE.Light),
      fillColor: (SMOKE_STYLE[f.properties.density] || SMOKE_STYLE.Light).color,
    }),
  });
  if (document.getElementById("toggle-smoke").checked) smokeLayer.addTo(map);
}

/* ---- rainfall radar ----
   A single tile layer whose URL is swapped per animation frame. Stacking one
   layer per frame (the old approach) kept every frame's tiles resident and
   crashed iOS Safari on pinch-zoom; one layer holds a bounded tile set. */
const radar = {
  host: "",
  frames: [],
  index: 0,
  timer: null,
  visible: true,
  animate: true,
  layer: null,
};

function frameUrl(frame) {
  return `${radar.host}${frame.path}/256/{z}/{x}/{y}/4/1_1.png`;
}

function showFrame(i) {
  const frame = radar.frames[i];
  if (!frame || !radar.layer) return;
  radar.index = i;
  radar.layer.setUrl(frameUrl(frame));
  const label = document.getElementById("radar-time");
  if (label) {
    label.textContent = new Date(frame.time * 1000).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    });
  }
}

function tick() {
  showFrame((radar.index + 1) % radar.frames.length);
}

function setAnimating(on) {
  clearInterval(radar.timer);
  radar.timer = null;
  if (on && radar.frames.length > 1) radar.timer = setInterval(tick, ANIMATION_MS);
  else if (radar.frames.length) showFrame(radar.frames.length - 1);
}

function setRadarVisible(on) {
  radar.visible = on;
  if (!radar.layer) return;
  if (on) {
    radar.layer.addTo(map);
    setAnimating(radar.animate);
  } else {
    setAnimating(false);
    map.removeLayer(radar.layer);
  }
}

async function loadRadar() {
  const data = await (await fetch(RAINVIEWER_INDEX)).json();
  radar.host = data.host;
  // Fewer frames on touch devices keeps the animation light on memory.
  radar.frames = (data.radar.past || []).slice(IS_TOUCH ? -6 : -10);
  if (!radar.frames.length) return;
  radar.layer = L.tileLayer(frameUrl(radar.frames[radar.frames.length - 1]), {
    opacity: 0.72,
    zIndex: 400,
    maxZoom: MAX_ZOOM,
    maxNativeZoom: 10,
    keepBuffer: 1,
    updateWhenIdle: IS_TOUCH,
    updateWhenZooming: false,
    attribution: '&copy; <a href="https://www.rainviewer.com/">RainViewer</a>',
  });
  if (radar.visible) radar.layer.addTo(map);
  radar.index = radar.frames.length - 1;
  setAnimating(radar.animate);
}

document.getElementById("toggle-smoke").addEventListener("change", (e) => {
  if (!smokeLayer) return;
  if (e.target.checked) smokeLayer.addTo(map);
  else map.removeLayer(smokeLayer);
});
document.querySelectorAll(".tabs [data-sort]").forEach((tab) => {
  tab.addEventListener("click", () => {
    listMode = tab.dataset.sort;
    document.querySelectorAll(".tabs [data-sort]").forEach((t) => {
      const active = t === tab;
      t.classList.toggle("active", active);
      t.setAttribute("aria-selected", String(active));
    });
    renderList(allFeatures);
  });
});
document.getElementById("toggle-rain").addEventListener("change", (e) => {
  setRadarVisible(e.target.checked);
});
document.getElementById("toggle-anim").addEventListener("change", (e) => {
  radar.animate = e.target.checked;
  if (radar.visible) setAnimating(radar.animate);
  else if (!radar.animate) setAnimating(false);
});
document.getElementById("toggle-fires").addEventListener("change", (e) => {
  if (e.target.checked) fireLayer.addTo(map);
  else map.removeLayer(fireLayer);
});

/* Mobile: panels collapse into toggle chips. */
document.querySelectorAll("[data-toggle-panel]").forEach((btn) => {
  btn.addEventListener("click", () => {
    const panel = document.querySelector(btn.dataset.togglePanel);
    const open = panel.classList.toggle("open");
    document
      .querySelectorAll(".panel.open")
      .forEach((p) => p !== panel && p.classList.remove("open"));
    btn.classList.toggle("active", open);
    document
      .querySelectorAll("[data-toggle-panel]")
      .forEach((b) => b !== btn && b.classList.remove("active"));
  });
});

loadFires().catch((err) => {
  console.error("fires failed", err);
  showBanner("Couldn't load fire data — retrying may help.");
});
loadSummary().catch((err) => console.error("summary failed", err));
loadRadar().catch((err) => console.error("radar failed", err));
loadSmoke().catch((err) => console.error("smoke failed", err));
