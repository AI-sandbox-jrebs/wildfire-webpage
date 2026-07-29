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

const nf = new Intl.NumberFormat("en-US");
const fmtAcres = (a) => (a == null ? "unknown" : `${nf.format(Math.round(a))} ac`);

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

function popupHtml(p) {
  const rows = [
    ["Size", fmtAcres(p.acres)],
    ["Contained", p.contained == null ? "—" : `${Math.round(p.contained)}%`],
    ["Started", p.discovered ? new Date(p.discovered).toLocaleDateString() : "—"],
    ["Cause", p.cause || "—"],
  ];
  if (p.rain) {
    rows.push(["Rain, past 7 d", `${p.rain.past_7d_mm} mm`]);
    rows.push(["Rain, next 3 d", `${p.rain.next_3d_mm} mm`]);
  }
  return `<div class="pop">
    <h3>${p.name}</h3>
    <div class="where">${p.state ? p.state + " · " : ""}${p.source === "WFIGS" ? "NIFC incident" : "NASA EONET event"}</div>
    <table>${rows.map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join("")}</table>
    ${sparkline(p.rain)}
  </div>`;
}

function renderList(features) {
  const list = document.getElementById("fire-list");
  const top = [...features]
    .filter((f) => f.properties.acres)
    .sort((a, b) => b.properties.acres - a.properties.acres)
    .slice(0, 25);
  list.innerHTML = top
    .map((f, i) => {
      const p = f.properties;
      const rain = p.rain ? `${p.rain.past_7d_mm} mm rain / 7 d` : "no rainfall sample";
      const wet = p.rain && p.rain.past_7d_mm >= 10 ? " wet" : "";
      return `<li data-key="${featureKey(f)}" tabindex="0">
        <span class="name">${i + 1}. ${p.name}</span>
        <span class="acres">${nf.format(Math.round(p.acres))}</span>
        <span class="meta${wet}">${p.state || "intl"} · ${rain}</span>
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
  if (on) radar.layer.addTo(map);
  else map.removeLayer(radar.layer);
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
    updateWhenIdle: true,
    updateWhenZooming: false,
    attribution: '&copy; <a href="https://www.rainviewer.com/">RainViewer</a>',
  });
  if (radar.visible) radar.layer.addTo(map);
  radar.index = radar.frames.length - 1;
  setAnimating(radar.animate);
}

document.getElementById("toggle-rain").addEventListener("change", (e) => {
  setRadarVisible(e.target.checked);
});
document.getElementById("toggle-anim").addEventListener("change", (e) => {
  radar.animate = e.target.checked;
  setAnimating(radar.animate);
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
