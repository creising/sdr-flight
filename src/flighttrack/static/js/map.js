import { altClass, isOverhead, escapeHtml, flightLevel, destPoint } from "/static/js/util.js";

let map, layer, acLayer, trailLayer, trackLayer;
const markers = new Map();   // icao -> L.marker
const trails = new Map();    // icao -> [[lat,lon], ...] (<=6)
const trailMarkers = new Map(); // icao -> [L.circleMarker]
let selectCb = null;
const RINGS_NMI = [5, 10, 20, 30];
const M_PER_NMI = 1852;

// Tracking: the full flown path (accumulated live) + a time-ahead heading ray
// for a single tracked aircraft. Owned entirely here, driven by opts.track.
const PROJECT_MIN = 5;              // look-ahead horizon for the projection ray
let trackPathIcao = null;           // which icao the current path belongs to
let trackPath = [];                 // [[lat,lon], ...] since tracking started
let trackLine = null, projLine = null;
const projWpts = [];                // per-minute waypoint dots + labels along the ray

function css(v) { return getComputedStyle(document.documentElement).getPropertyValue(v).trim(); }
function altColorVar(cls) { return cls ? `var(--alt-${cls})` : "var(--muted)"; }

const HOME_ZOOM = 10;
let homeLatLon = null;   // receiver position, for the re-center button

export function initMap(receiver) {
  homeLatLon = [receiver.lat, receiver.lon];
  map = L.map("map", { zoomControl: false, attributionControl: false })
    .setView([receiver.lat, receiver.lon], HOME_ZOOM);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    { maxZoom: 18 }).addTo(map);
  layer = L.layerGroup().addTo(map);       // rings + home
  trailLayer = L.layerGroup().addTo(map);
  trackLayer = L.layerGroup().addTo(map);  // tracked flight: path + projection
  acLayer = L.layerGroup().addTo(map);

  for (const nmi of RINGS_NMI) {
    const radiusM = nmi * M_PER_NMI;
    L.circle([receiver.lat, receiver.lon], {
      radius: radiusM, fill: false, color: css("--ring") || "#2a3542",
      weight: 1, interactive: false,
    }).addTo(layer);
    const edge = L.latLng(receiver.lat + radiusM / 111000, receiver.lon);
    L.marker(edge, { interactive: false, keyboard: false, icon: L.divIcon({
      className: "", html: `<div class="ring-label">${nmi} nmi</div>`,
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

function icon(a, opts = {}) {
  const cls = altClass(a.alt_ft);
  const color = altColorVar(cls);
  const selected = opts.selected && a.icao === opts.selected;
  const ring = isOverhead(a.elevation_deg)
    ? `<circle cx="17" cy="17" r="16" fill="none" stroke="${color}" stroke-opacity="0.55" stroke-width="1.5"/>`
    : "";
  const sel = selected
    ? `<circle cx="17" cy="17" r="15" fill="none" stroke="var(--text)" stroke-width="1.5" stroke-dasharray="3 3"/>`
    : "";
  const halo = a.visible
    ? `<circle cx="17" cy="17" r="16" fill="${color}" opacity="0.18" class="ac-halo"/>`
    : "";
  const label = opts.labelsOn
    ? `<div class="ac-label"><span class="al-call">${escapeHtml((a.callsign || a.icao || "").toUpperCase())}</span>` +
      `<span class="al-fl" style="color:${color}">FL${flightLevel(a.alt_ft)}</span></div>`
    : "";
  return L.divIcon({
    className: "", iconSize: [34, 34], iconAnchor: [17, 17],
    html: `<div class="ac-wrap${selected ? " selected" : ""}">` +
      `<svg width="34" height="34" viewBox="0 0 34 34">${halo}${ring}${sel}` +
      `<g transform="translate(5,5) rotate(${a.track_deg ?? 0} 12 12)">` +
      `<polygon class="ac-marker" points="12,1 21,22 12,17 3,22" fill="${color}" ` +
      `stroke="var(--bg)" stroke-width="1.5"/></g></svg>${label}</div>`,
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

export function renderAircraft(list, opts = {}) {
  const seen = new Set();
  for (const a of list) {
    if (a.lat == null || a.lon == null) continue;
    seen.add(a.icao);
    const cls = altClass(a.alt_ft);
    let m = markers.get(a.icao);
    if (!m) {
      m = L.marker([a.lat, a.lon], { icon: icon(a, opts) }).addTo(acLayer);
      m.on("click", () => selectCb && selectCb(a.icao));
      markers.set(a.icao, m);
    } else {
      m.setLatLng([a.lat, a.lon]); m.setIcon(icon(a, opts));
    }
    m.bindTooltip(escapeHtml((a.callsign || a.icao || "").toUpperCase()));
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
  updateTrack(list, opts.track);
}

// Accumulate and draw the tracked flight's flown path + time-ahead heading ray.
function updateTrack(list, trackIcao) {
  if (trackIcao !== trackPathIcao) {
    clearTrack();
    trackPathIcao = trackIcao;
    // Seed with the trail already on the map so a path is visible immediately.
    if (trackIcao) trackPath = (trails.get(trackIcao) || []).slice();
  }
  if (!trackIcao) return;
  const a = list.find((x) => x.icao === trackIcao);
  if (!a || a.lat == null || a.lon == null) return;   // keep existing path if it blinks out

  // Append the new position (skip duplicates so a parked plane doesn't pile points).
  const last = trackPath[trackPath.length - 1];
  if (!last || last[0] !== a.lat || last[1] !== a.lon) trackPath.push([a.lat, a.lon]);

  const color = css(`--alt-${altClass(a.alt_ft)}`) || css("--text") || "#e8edf2";
  if (!trackLine) trackLine = L.polyline(trackPath, {
    className: "track-path", color, weight: 3, opacity: 1, interactive: false,
  }).addTo(trackLayer);
  else { trackLine.setLatLngs(trackPath); trackLine.setStyle({ color }); }

  // Time-ahead projection: a heading ray with a waypoint dot every minute,
  // labelled with the minutes-ahead, out to PROJECT_MIN at current ground speed.
  const gs = a.ground_speed_kt, trk = a.track_deg;
  if (gs == null || gs <= 0 || trk == null) { clearProjection(); return; }
  const end = destPoint(a.lat, a.lon, trk, gs * (PROJECT_MIN / 60));
  if (!projLine) projLine = L.polyline([[a.lat, a.lon], end], {
    className: "track-projection", color, weight: 2.5, opacity: 0.75,
    dashArray: "6 6", interactive: false,
  }).addTo(trackLayer);
  else { projLine.setLatLngs([[a.lat, a.lon], end]); projLine.setStyle({ color }); }

  for (const m of projWpts) trackLayer.removeLayer(m);
  projWpts.length = 0;
  for (let k = 1; k <= PROJECT_MIN; k++) {
    const wp = destPoint(a.lat, a.lon, trk, gs * (k / 60));
    projWpts.push(L.circleMarker(wp, {
      radius: 3, color, fillColor: color, fillOpacity: 1, weight: 0, interactive: false,
    }).addTo(trackLayer));
    projWpts.push(L.marker(wp, { interactive: false, keyboard: false, icon: L.divIcon({
      className: "", html: `<div class="wp-label">${k}′</div>`,
      iconSize: [22, 12], iconAnchor: [-5, 6],
    }) }).addTo(trackLayer));
  }
}

function clearProjection() {
  if (projLine) { trackLayer.removeLayer(projLine); projLine = null; }
  for (const m of projWpts) trackLayer.removeLayer(m);
  projWpts.length = 0;
}

function clearTrack() {
  if (trackLine) { trackLayer.removeLayer(trackLine); trackLine = null; }
  clearProjection();
  trackPath = [];
}

export function onSelect(cb) { selectCb = cb; }
export function panTo(icao) { const m = markers.get(icao); if (m && map) map.panTo(m.getLatLng()); }
export function recenterMap() { if (map && homeLatLon) map.setView(homeLatLon, HOME_ZOOM); }
export function getMap() { return map; }

export function clearAircraft() {
  for (const [, m] of markers) acLayer.removeLayer(m);
  markers.clear();
  for (const [, ms] of trailMarkers) for (const t of ms) trailLayer.removeLayer(t);
  trailMarkers.clear(); trails.clear();
  clearTrack(); trackPathIcao = null;
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

export function renderReplay(tracks, t, opts = {}) {
  const list = [];
  for (const tr of tracks) {
    const p = interp(tr.points, t);
    if (p) list.push({ icao: tr.icao, callsign: tr.callsign, lat: p.lat, lon: p.lon,
                       alt_ft: p.alt_ft, track_deg: p.track_deg });
  }
  renderAircraft(list, opts);
  return list.length;
}
