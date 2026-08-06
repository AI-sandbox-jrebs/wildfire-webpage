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
    <div class="where">${p.state ? p.state + " · " : ""}NIFC incident</div>
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
  document.getElementById("stat-dry-scope").textContent =
    `of ${nf.format(s.rainfall_sampled)} largest fires`;
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

/* ---- public updates view ---- */
let changelogPromise = null;

function textNode(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.textContent = text;
  return node;
}

function renderUpdates(entries) {
  const list = document.getElementById("updates-list");
  list.replaceChildren();
  entries.forEach((entry) => {
    const card = document.createElement("article");
    card.className = `update-card update-card--${entry.kind}`;

    const top = document.createElement("div");
    top.className = "update-card__top";
    top.append(textNode("time", "", entry.date), textNode("span", `update-kind update-kind--${entry.kind}`, entry.kind));
    card.append(top, textNode("h2", "", entry.title), textNode("p", "update-card__summary", entry.summary));

    if (entry.impact) {
      const impact = document.createElement("dl");
      impact.className = "update-impact";
      [["Before", entry.impact.before], ["After", entry.impact.after]].forEach(([label, value]) => {
        const box = document.createElement("div");
        box.append(textNode("dt", "", label), textNode("dd", "", value));
        impact.append(box);
      });
      card.append(impact);
    }

    const details = document.createElement("ul");
    entry.details.forEach((detail) => details.append(textNode("li", "", detail)));
    card.append(details);

    if (entry.note) card.append(textNode("p", "update-card__note", entry.note));
    if (entry.pr) {
      const link = document.createElement("a");
      link.className = "update-card__audit";
      link.href = `https://github.com/AI-sandbox-jrebs/wildfire-webpage/pull/${entry.pr}`;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = `Inspect pull request #${entry.pr}`;
      card.append(link);
    }
    list.append(card);
  });
}

async function loadUpdates() {
  if (!changelogPromise) {
    changelogPromise = fetch(`data/changelog.json?v=${Date.now()}`).then((res) => {
      if (!res.ok) throw new Error(`changelog request failed: ${res.status}`);
      return res.json();
    }).then((entries) => {
      renderUpdates(entries);
      return entries;
    });
  }
  try {
    await changelogPromise;
  } catch (err) {
    console.error("updates failed", err);
    const status = document.getElementById("updates-status");
    status.hidden = false;
    status.textContent = "Updates are temporarily unavailable. Please try again later.";
  }
}

/* ---- long-term history view ---- */
let historyPromise = null;
const SVG_NS = "http://www.w3.org/2000/svg";

function svgNode(tag, attrs) {
  const node = document.createElementNS(SVG_NS, tag);
  Object.entries(attrs || {}).forEach(([key, value]) => node.setAttribute(key, value));
  return node;
}

function historySeries(data, key) {
  return data.series && data.series[key] && data.series[key].records
    ? data.series[key].records
    : null;
}

function formatHistoryNumber(value, decimals = 0) {
  if (value === null || value === undefined || Number.isNaN(value)) return "Unavailable";
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: decimals }).format(value);
}

function makeHistoryChart(targetId, config, records, selectedYear) {
  const target = document.getElementById(targetId);
  target.replaceChildren();
  const card = document.createElement("article");
  card.className = `history-chart${config.wide ? " history-chart--wide" : ""}`;
  card.append(textNode("h2", "", config.title), textNode("p", "history-chart__note", config.note));
  if (!records || !records.length) {
    card.append(textNode("p", "history-unavailable", "This series is currently unavailable."));
    target.append(card);
    return;
  }

  const values = records.map((record) => Number(config.value(record)));
  const finite = values.filter(Number.isFinite);
  const min = config.zero ? 0 : Math.min(0, ...finite);
  const max = Math.max(1, ...finite);
  const width = 760;
  const height = 190;
  const left = 38;
  const right = 8;
  const top = 12;
  const bottom = 28;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const svg = svgNode("svg", {
    viewBox: `0 0 ${width} ${height}`,
    role: "img",
    "aria-label": config.aria,
  });
  const title = svgNode("title");
  title.textContent = config.title;
  const desc = svgNode("desc");
  desc.textContent = config.aria;
  svg.append(title, desc);
  [0, 0.5, 1].forEach((fraction) => {
    const y = top + plotHeight * fraction;
    svg.append(svgNode("line", { x1: left, x2: width - right, y1: y, y2: y, class: "gridline" }));
    const label = svgNode("text", { x: left - 6, y: y + 3, "text-anchor": "end" });
    label.textContent = formatHistoryNumber(max - (max - min) * fraction, config.decimals || 0);
    svg.append(label);
  });
  svg.append(svgNode("line", { x1: left, x2: width - right, y1: top + plotHeight, y2: top + plotHeight, class: "axis" }));

  const xFor = (index) => left + (records.length === 1 ? plotWidth / 2 : (index / (records.length - 1)) * plotWidth);
  const yFor = (value) => top + ((max - value) / (max - min || 1)) * plotHeight;
  if (config.type === "bar") {
    const barWidth = Math.max(2, plotWidth / records.length - 1.5);
    records.forEach((record, index) => {
      const value = values[index];
      if (!Number.isFinite(value)) return;
      const x = xFor(index) - barWidth / 2;
      const y = yFor(value);
      const rect = svgNode("rect", {
        x, y, width: barWidth, height: Math.max(1, top + plotHeight - y),
        class: `bar ${config.primary ? "bar--primary" : ""}${record.year === selectedYear ? " bar--selected" : ""}`,
      });
      if (config.flag && record.count_flag) rect.setAttribute("opacity", "0.35");
      svg.append(rect);
    });
  } else {
    const points = records.map((record, index) => `${xFor(index)},${yFor(values[index])}`).join(" ");
    svg.append(svgNode("polyline", { points, class: `line ${config.lineClass || ""}` }));
    records.forEach((record, index) => {
      if (!Number.isFinite(values[index]) || record.year !== selectedYear) return;
      svg.append(svgNode("circle", { cx: xFor(index), cy: yFor(values[index]), r: 4, class: "point point--selected" }));
    });
  }
  const first = svgNode("text", { x: left, y: height - 7 });
  first.textContent = records[0].year;
  const last = svgNode("text", { x: width - right, y: height - 7, "text-anchor": "end" });
  last.textContent = records[records.length - 1].year;
  svg.append(first, last);
  if (config.flag) {
    const flag = svgNode("text", { x: xFor(0), y: top - 1, class: "selected" });
    flag.textContent = "1983–84 counts flagged";
    svg.append(flag);
  }
  card.append(svg);
  target.append(card);
}

function renderHistoryYear(data, year) {
  const context = data.derived && data.derived.year_context
    ? data.derived.year_context[String(year)]
    : null;
  document.getElementById("history-year-value").textContent = year;
  const facts = document.getElementById("history-year-facts");
  facts.replaceChildren();
  [
    ["Fires", context && context.fires !== undefined ? formatHistoryNumber(context.fires) : null, context && context.count_flag ? "early count flagged" : ""],
    ["Acres burned", context && context.acres !== undefined ? `${formatHistoryNumber(context.acres)} ac` : null, context && context.acre_rank ? `#${context.acre_rank} by acres` : ""],
    ["Average fire size", context && context.acres_per_fire ? `${formatHistoryNumber(context.acres_per_fire, 1)} ac` : null, ""],
    ["Precipitation", context && context.precipitation !== undefined ? `${formatHistoryNumber(context.precipitation, 2)} in` : null, context && context.precipitation_anomaly !== undefined ? `${context.precipitation_anomaly >= 0 ? "+" : ""}${formatHistoryNumber(context.precipitation_anomaly, 2)} vs baseline` : ""],
    ["USDM D1+", context && context.drought !== undefined ? `${formatHistoryNumber(context.drought, 1)}%` : null, "annual weekly mean"],
  ].forEach(([label, value, note]) => {
    const fact = document.createElement("div");
    fact.className = "history-fact";
    fact.append(textNode("span", "history-fact__label", label), textNode("strong", "history-fact__value", value || "Unavailable"));
    if (note) fact.append(textNode("small", "history-fact__note", note));
    facts.append(fact);
  });
}

function renderHistorySources(data) {
  const list = document.getElementById("history-source-list");
  list.replaceChildren();
  Object.entries(data.sources || {}).forEach(([key, sourceStatus]) => {
    const metadata = sourceStatus.metadata || (data.series && data.series[key] && data.series[key].metadata) || {};
    const source = document.createElement("article");
    source.className = "history-source";
    const title = textNode("h3", "", metadata.name || key);
    const status = sourceStatus.status === "failed"
      ? " · refresh failed; showing last good copy"
      : "";
    title.append(textNode("span", "history-source__status", status));
    source.append(title);
    source.append(textNode("p", "", `${metadata.coverage_start}–${metadata.coverage_end} · ${metadata.units} · ${metadata.geography}`));
    source.append(textNode("p", "", `${metadata.aggregation}${metadata.baseline ? ` Baseline: ${metadata.baseline_period} mean (${metadata.baseline} in).` : ""}`));
    if (metadata.url) source.append(textNode("p", "", `Data URL: ${metadata.url}`));
    const link = document.createElement("a");
    link.href = metadata.landing_page;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = "Official source and documentation";
    source.append(link);
    const caveats = document.createElement("ul");
    (metadata.caveats || []).forEach((caveat) => caveats.append(textNode("li", "", caveat)));
    source.append(caveats);
    list.append(source);
  });
}

const HISTORY_CHARTS = [
  {
    id: "history-chart-acres",
    series: "nifc",
    title: "Acres burned per year",
    note: "NIFC national total; acreage is the more comparable long-run signal.",
    type: "bar",
    primary: true,
    zero: true,
    wide: true,
    value: (record) => record.acres,
    aria: "Annual NIFC acres burned, with the largest years clustered after 2000.",
  },
  {
    id: "history-chart-size",
    series: "nifc",
    title: "Average fire size",
    note: "NIFC acres divided by fires; 1983–84 are excluded from this count-based measure.",
    type: "line",
    zero: true,
    lineClass: "line--warm",
    wide: true,
    value: (record) => record.acres_per_fire,
    aria: "Average acres per fire rises substantially in the recent record.",
  },
  {
    id: "history-chart-fires",
    series: "nifc",
    title: "Fires per year",
    note: "NIFC counts; 1983–84 are visibly flagged for incomplete reporting.",
    type: "bar",
    zero: true,
    flag: true,
    value: (record) => record.fires,
    aria: "Annual fire counts are flat to lower than the 1990s after excluding incomplete 1983–84 counts.",
  },
  {
    id: "history-chart-precipitation",
    series: "noaa_pcp",
    title: "Annual precipitation anomaly",
    note: "NOAA CONUS January–December precipitation minus the full-record mean baseline.",
    type: "line",
    value: (record) => record.anomaly,
    aria: "Annual contiguous US precipitation anomaly relative to the full-record mean.",
  },
  {
    id: "history-chart-temperature",
    series: "noaa_tavg",
    title: "Average temperature",
    note: "NOAA CONUS January–December average temperature.",
    type: "line",
    lineClass: "line--warm",
    value: (record) => record.value,
    aria: "Annual contiguous US average temperature over the NOAA record.",
  },
  {
    id: "history-chart-drought",
    series: "usdm",
    title: "US area in D1+ drought",
    note: "US Drought Monitor annual mean of weekly D1-or-worse values.",
    type: "line",
    lineClass: "line--dry",
    zero: true,
    value: (record) => record.value,
    aria: "Annual mean percent of contiguous US area in D1 or worse drought over the USDM record.",
  },
  {
    id: "history-chart-mtbs",
    series: "mtbs",
    title: "MTBS mapped burned area",
    note: "Separate mapped product; do not add this series to NIFC totals.",
    type: "bar",
    zero: true,
    value: (record) => record.acres,
    aria: "Annual mapped burned area from MTBS, presented separately from NIFC all-fire totals.",
  },
];

function drawHistoryCharts(data, selectedYear) {
  HISTORY_CHARTS.forEach((config) => {
    makeHistoryChart(config.id, config, historySeries(data, config.series), selectedYear);
  });
}

function renderHistory(data) {
  const derived = data.derived;
  const verdict = document.getElementById("history-verdict");
  if (!derived) {
    verdict.textContent = "The long-term comparison is not available yet.";
    return;
  }
  verdict.textContent =
    `Fire numbers are not rising: the annual average fell from ${formatHistoryNumber(derived.early_count_average)} fires in ${derived.early_count_label} to ${formatHistoryNumber(derived.recent_count_average)} in ${derived.recent_count_label}. ` +
    `But the average fire grew from ${formatHistoryNumber(derived.early_acres_per_fire, 1)} to ${formatHistoryNumber(derived.recent_acres_per_fire, 1)} acres — ${formatHistoryNumber(derived.recent_size_multiplier, 1)}× larger — and ${derived.top_10_sentence.toLowerCase()}.`;
  document.getElementById("history-caveat").textContent = derived.count_comparison_note;
  const nifc = historySeries(data, "nifc");
  const yearInput = document.getElementById("history-year");
  yearInput.min = nifc ? nifc[0].year : 1983;
  yearInput.max = nifc ? nifc[nifc.length - 1].year : 2025;
  const selectedYear = Math.max(Number(yearInput.min), Math.min(Number(yearInput.max), Number(yearInput.value)));
  yearInput.value = selectedYear;
  renderHistoryYear(data, selectedYear);
  drawHistoryCharts(data, selectedYear);
  renderHistorySources(data);
  yearInput.oninput = () => {
    const year = Number(yearInput.value);
    renderHistoryYear(data, year);
    drawHistoryCharts(data, year);
  };
}

async function loadHistory() {
  if (!historyPromise) {
    historyPromise = fetch(`data/longterm.json?v=${Date.now()}`).then((res) => {
      if (!res.ok) throw new Error(`long-term history request failed: ${res.status}`);
      return res.json();
    }).then((data) => {
      renderHistory(data);
      return data;
    });
  }
  try {
    await historyPromise;
  } catch (err) {
    console.error("history failed", err);
    const status = document.getElementById("history-status");
    status.hidden = false;
    status.textContent = "Long-term history is temporarily unavailable. The live map and Updates view are still available.";
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

const VIEW_DEFS = [
  { id: "now", hash: "", onEnter: () => requestAnimationFrame(() => map.invalidateSize()) },
  { id: "updates", hash: "updates", onEnter: loadUpdates },
  { id: "then-vs-now", hash: "then-vs-now", onEnter: loadHistory },
];
const viewByHash = new Map(VIEW_DEFS.map((view) => [view.hash, view]));
let activeView = null;

function viewFromLocation() {
  return viewByHash.get(location.hash.replace(/^#\/?/, "")) || VIEW_DEFS[0];
}

function applyView(view) {
  activeView = view;
  document.body.dataset.view = view.id;
  const updates = document.getElementById("updates-view");
  updates.hidden = view.id !== "updates";
  const history = document.getElementById("history-view");
  history.hidden = view.id !== "then-vs-now";
  document.querySelectorAll(".view-nav [data-view]").forEach((button) => {
    const current = button.dataset.view === view.id;
    button.setAttribute("aria-current", current ? "page" : "false");
  });
  view.onEnter();
}

function navigateView(id) {
  const view = VIEW_DEFS.find((candidate) => candidate.id === id) || VIEW_DEFS[0];
  const hash = `#/${view.hash}`;
  if (location.hash !== hash) history.pushState({}, "", hash);
  applyView(view);
}

document.querySelectorAll(".view-nav [data-view]").forEach((button) => {
  button.addEventListener("click", (event) => {
    event.preventDefault();
    navigateView(button.dataset.view);
  });
});
window.addEventListener("hashchange", () => applyView(viewFromLocation()));
window.addEventListener("popstate", () => applyView(viewFromLocation()));
applyView(viewFromLocation());

loadFires().catch((err) => {
  console.error("fires failed", err);
  showBanner("Couldn't load fire data — retrying may help.");
});
loadSummary().catch((err) => console.error("summary failed", err));
loadRadar().catch((err) => console.error("radar failed", err));
loadSmoke().catch((err) => console.error("smoke failed", err));
