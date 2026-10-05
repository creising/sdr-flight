import { altClass, isOverhead } from "/static/js/util.js";

let map, layer, acLayer, trailLayer;
const markers = new Map();   // icao -> L.marker
const trails = new Map();    // icao -> [[lat,lon], ...] (<=6)
const trailMarkers = new Map(); // icao -> [L.circleMarker]
let selectCb = null;
const RINGS_KM = [5, 10, 20, 30];

function css(v) { return getComputedStyle(document.documentElement).getPropertyValue(v).trim(); }
function altColorVar(cls) { return cls ? `var(--alt-${cls})` : "var(--muted)"; }

export function initMap(receiver) {
  map = L.map("map", { zoomControl: false, attributionControl: false })
    .setView([receiver.lat, receiver.lon], 10);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    { maxZoom: 18 }).addTo(map);
  layer = L.layerGroup().addTo(map);       // rings + home
  trailLayer = L.layerGroup().addTo(map);
  acLayer = L.layerGroup().addTo(map);

  for (const km of RINGS_KM) {
    L.circle([receiver.lat, receiver.lon], {
      radius: km * 1000, fill: false, color: css("--ring") || "#2a3542",
      weight: 1, interactive: false,
    }).addTo(layer);
    const edge = L.latLng(receiver.lat + km / 111, receiver.lon);
    L.marker(edge, { interactive: false, keyboard: false, icon: L.divIcon({
      className: "", html: `<div class="ring-label">${km} km</div>`,
      iconSize: [44, 14], iconAnchor: [22, 7],
    }) }).addTo(layer);
  }
  // Home crosshair: ring + center dot
  L.circleMarker([receiver.lat, receiver.lon], {
    radius: 8, color: css("--text") || "#e8edf2", weight: 2, fill: false, interactive: false,
  }).addTo(layer);
  L.circleMarker([receiver.lat, receiver.lon], {
    radius: 2, color: css("--text") || "#e8edf2", fillColor: css("--text") || "#e8edf2",
    fillOpacity: 1, weight: 0, interactive: false,
  }).addTo(layer);
  return map;
}

function icon(a) {
  const cls = altClass(a.alt_ft);
  const color = altColorVar(cls);
  const ring = isOverhead(a.elevation_deg)
    ? `<circle cx="17" cy="17" r="16" fill="none" stroke="${color}" stroke-opacity="0.55" stroke-width="1.5"/>`
    : "";
  return L.divIcon({
    className: "", iconSize: [34, 34], iconAnchor: [17, 17],
    html: `<svg width="34" height="34" viewBox="0 0 34 34">${ring}` +
      `<g transform="translate(5,5) rotate(${a.track_deg ?? 0} 12 12)">` +
      `<polygon class="ac-marker" points="12,1 21,22 12,17 3,22" fill="${color}" ` +
      `stroke="var(--bg)" stroke-width="1.5"/></g></svg>`,
  });
}

function drawTrail(icao, cls) {
  for (const m of (trailMarkers.get(icao) || [])) trailLayer.removeLayer(m);
  const pts = trails.get(icao) || [];
  const ms = [];
  pts.forEach((p, i) => {
    const op = 0.6 * ((i + 1) / pts.length) + 0.05;  // oldest faint -> newest brighter
    ms.push(L.circleMarker(p, {
      radius: 2.5, color: altColorVar(cls), fillColor: altColorVar(cls),
      fillOpacity: op, opacity: op, weight: 0, interactive: false,
    }).addTo(trailLayer));
  });
  trailMarkers.set(icao, ms);
}

export function renderAircraft(list) {
  const seen = new Set();
  for (const a of list) {
    if (a.lat == null || a.lon == null) continue;
    seen.add(a.icao);
    const cls = altClass(a.alt_ft);
    let m = markers.get(a.icao);
    if (!m) {
      m = L.marker([a.lat, a.lon], { icon: icon(a) }).addTo(acLayer);
      m.on("click", () => selectCb && selectCb(a.icao));
      markers.set(a.icao, m);
    } else {
      m.setLatLng([a.lat, a.lon]); m.setIcon(icon(a));
    }
    m.bindTooltip(a.callsign || a.icao);
    const tr = trails.get(a.icao) || []; tr.push([a.lat, a.lon]);
    while (tr.length > 6) tr.shift();
    trails.set(a.icao, tr);
    drawTrail(a.icao, cls);
  }
  for (const [icao, m] of markers) if (!seen.has(icao)) {
    acLayer.removeLayer(m); markers.delete(icao);
    for (const t of (trailMarkers.get(icao) || [])) trailLayer.removeLayer(t);
    trailMarkers.delete(icao); trails.delete(icao);
  }
}

export function onSelect(cb) { selectCb = cb; }
export function panTo(icao) { const m = markers.get(icao); if (m && map) map.panTo(m.getLatLng()); }
export function getMap() { return map; }

export function clearAircraft() {
  for (const [, m] of markers) acLayer.removeLayer(m);
  markers.clear();
  for (const [, ms] of trailMarkers) for (const t of ms) trailLayer.removeLayer(t);
  trailMarkers.clear(); trails.clear();
}

function interp(points, t) {
  if (!points.length || t < points[0].ts || t > points[points.length - 1].ts) return null;
  let lo = points[0];
  for (const p of points) {
    if (p.ts === t) return p;
    if (p.ts > t) {
      const f = (t - lo.ts) / (p.ts - lo.ts || 1);
      return { lat: lo.lat + (p.lat - lo.lat) * f, lon: lo.lon + (p.lon - lo.lon) * f,
               alt_ft: lo.alt_ft, track_deg: p.track_deg ?? lo.track_deg };
    }
    lo = p;
  }
  return lo;
}

export function renderReplay(tracks, t) {
  const list = [];
  for (const tr of tracks) {
    const p = interp(tr.points, t);
    if (p) list.push({ icao: tr.icao, callsign: tr.callsign, lat: p.lat, lon: p.lon,
                       alt_ft: p.alt_ft, track_deg: p.track_deg });
  }
  renderAircraft(list);
  return list.length;
}
