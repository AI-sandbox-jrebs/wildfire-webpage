/* Wildfire + rainfall map. Data is baked into data/ at build time; the rain
   radar is fetched live from RainViewer at page load. */

const RAINVIEWER_INDEX = "https://api.rainviewer.com/public/weather-maps.json";
const ANIMATION_MS = 700;

const map = L.map("map", {
  center: [39.5, -108],
  zoom: 5,
  minZoom: 2,
  zoomControl: false,
  worldCopyJump: true,
});
L.control.zoom({ position: "bottomright" }).addTo(map);

L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
  attribution: '&copy; OpenStreetMap &copy; CARTO',
  maxZoom: 18,
}).addTo(map);
L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_only_labels/{z}/{x}/{y}{r}.png", {
  maxZoom: 18,
  pane: "shadowPane",
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
  map.on("zoomend", () => {
    const z = zoomFactor();
    markersByKey.forEach((m) => m.setRadius(m.baseRadius * z));
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

/* ---- rainfall radar ---- */
const radar = { frames: [], layers: [], index: 0, timer: null, visible: true, animate: true };

function radarLayer(host, frame) {
  return L.tileLayer(`${host}${frame.path}/512/{z}/{x}/{y}/4/1_1.png`, {
    opacity: 0,
    zIndex: 400,
    maxZoom: 12,
    attribution: '&copy; <a href="https://www.rainviewer.com/">RainViewer</a>',
  });
}

function showFrame(i) {
  radar.layers.forEach((layer, idx) => layer.setOpacity(idx === i && radar.visible ? 0.75 : 0));
  const t = radar.frames[i];
  document.getElementById("radar-time").textContent = t
    ? new Date(t.time * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : "–";
}

function tick() {
  radar.index = (radar.index + 1) % radar.layers.length;
  showFrame(radar.index);
}

function setAnimating(on) {
  clearInterval(radar.timer);
  radar.timer = null;
  if (on && radar.layers.length > 1) radar.timer = setInterval(tick, ANIMATION_MS);
  else if (radar.layers.length) {
    radar.index = radar.layers.length - 1;
    showFrame(radar.index);
  }
}

async function loadRadar() {
  const data = await (await fetch(RAINVIEWER_INDEX)).json();
  radar.frames = (data.radar.past || []).slice(-12);
  radar.layers = radar.frames.map((f) => radarLayer(data.host, f).addTo(map));
  showFrame(radar.layers.length - 1);
  setAnimating(radar.animate);
}

document.getElementById("toggle-rain").addEventListener("change", (e) => {
  radar.visible = e.target.checked;
  showFrame(radar.index);
});
document.getElementById("toggle-anim").addEventListener("change", (e) => {
  radar.animate = e.target.checked;
  setAnimating(radar.animate);
});
document.getElementById("toggle-fires").addEventListener("change", (e) => {
  if (e.target.checked) fireLayer.addTo(map);
  else map.removeLayer(fireLayer);
});

loadFires().catch((err) => console.error("fires failed", err));
loadSummary().catch((err) => console.error("summary failed", err));
loadRadar().catch((err) => console.error("radar failed", err));
