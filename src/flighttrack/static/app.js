let map, youMarker, ws = null;
const markers = new Map(); // icao -> L.marker
let mode = "live";
let tracks = [];           // [{icao, callsign, points:[{ts,lat,lon,alt_ft,track_deg}]}]
let winStart = 0, winEnd = 0, playT = 0, playing = false, speed = 5, raf = null, lastFrame = 0;

function altColor(ft) {
  if (ft == null) return "#9aa7b2";
  if (ft < 10000) return "#ff5d5d";
  if (ft < 25000) return "#ffb24d";
  return "#5dd0ff";
}

function planeIcon(a) {
  const rot = a.track_deg ?? 0;
  return L.divIcon({ className: "",
    html: `<div class="plane" style="transform: rotate(${rot}deg); color:${altColor(a.alt_ft)}">✈</div>`,
    iconSize: [20, 20], iconAnchor: [10, 10] });
}

function renderContacts(list) {
  const ul = document.getElementById("contacts");
  ul.innerHTML = "";
  for (const a of list) {
    const li = document.createElement("li");
    const dist = a.distance_km != null ? `${a.distance_km.toFixed(1)} km` : "—";
    const alt = a.alt_ft != null ? `${Math.round(a.alt_ft).toLocaleString()} ft` : "—";
    li.innerHTML = `<div class="cs">${a.callsign || a.icao}</div>` +
                   `<div class="meta">${dist} · ${alt} · ${Math.round(a.elevation_deg ?? 0)}°</div>`;
    ul.appendChild(li);
  }
}

function renderAircraft(list) {
  const seen = new Set();
  for (const a of list) {
    seen.add(a.icao);
    let m = markers.get(a.icao);
    if (!m) { m = L.marker([a.lat, a.lon], { icon: planeIcon(a) }).addTo(map); markers.set(a.icao, m); }
    else { m.setLatLng([a.lat, a.lon]); m.setIcon(planeIcon(a)); }
    m.bindTooltip(a.callsign || a.icao);
  }
  for (const [icao, m] of markers) if (!seen.has(icao)) { map.removeLayer(m); markers.delete(icao); }
  renderContacts(list);
}

// ---- Live ----
function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws/live`);
  ws.onmessage = (e) => { if (mode === "live") { const d = JSON.parse(e.data); renderAircraft(d.aircraft);
    document.getElementById("status").textContent = `${d.aircraft.length} aircraft · live`; } };
  ws.onclose = () => { if (mode === "live") { document.getElementById("status").textContent = "reconnecting…";
    setTimeout(connect, 2000); } };
}

// ---- Playback ----
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

function renderPlaybackFrame() {
  const list = [];
  for (const tr of tracks) {
    const p = interp(tr.points, playT);
    if (p) list.push({ icao: tr.icao, callsign: tr.callsign, lat: p.lat, lon: p.lon,
                       alt_ft: p.alt_ft, track_deg: p.track_deg, distance_km: null, elevation_deg: null });
  }
  renderAircraft(list);
  const pct = winEnd > winStart ? ((playT - winStart) / (winEnd - winStart)) * 1000 : 0;
  document.getElementById("scrubber").value = String(pct);
  document.getElementById("playtime").textContent =
    `${new Date(playT * 1000).toLocaleTimeString()} · ${list.length} shown`;
  document.getElementById("status").textContent = "playback";
}

function tick(now) {
  if (!playing) return;
  const dt = (now - lastFrame) / 1000; lastFrame = now;
  playT = Math.min(winEnd, playT + dt * speed);
  renderPlaybackFrame();
  if (playT >= winEnd) { playing = false; document.getElementById("playpause").textContent = "▶"; return; }
  raf = requestAnimationFrame(tick);
}

async function loadWindow() {
  const span = Number(document.getElementById("window").value);
  winEnd = Date.now() / 1000; winStart = winEnd - span; playT = winStart;
  tracks = await (await fetch(`/api/history?from=${winStart}&to=${winEnd}`)).json();
  renderPlaybackFrame();
}

function setMode(next) {
  mode = next;
  document.getElementById("mode-live").classList.toggle("active", next === "live");
  document.getElementById("mode-playback").classList.toggle("active", next === "playback");
  document.getElementById("playback-controls").hidden = next !== "playback";
  playing = false; if (raf) cancelAnimationFrame(raf);
  document.getElementById("playpause").textContent = "▶";
  for (const [, m] of markers) map.removeLayer(m);
  markers.clear();
  if (next === "playback") loadWindow();
  else document.getElementById("status").textContent = "live";
}

async function init() {
  const cfg = await (await fetch("/api/config")).json();
  const { lat, lon } = cfg.receiver;
  map = L.map("map").setView([lat, lon], 9);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    { attribution: "© OpenStreetMap", maxZoom: 18 }).addTo(map);
  youMarker = L.circleMarker([lat, lon], { radius: 6, color: "#4de6a1", fillOpacity: 1 })
    .addTo(map).bindTooltip("You");

  document.getElementById("mode-live").onclick = () => setMode("live");
  document.getElementById("mode-playback").onclick = () => setMode("playback");
  document.getElementById("window").onchange = loadWindow;
  document.getElementById("speed").onchange = (e) => { speed = Number(e.target.value); };
  document.getElementById("scrubber").oninput = (e) => {
    playT = winStart + (Number(e.target.value) / 1000) * (winEnd - winStart);
    renderPlaybackFrame();
  };
  document.getElementById("playpause").onclick = () => {
    playing = !playing;
    document.getElementById("playpause").textContent = playing ? "❚❚" : "▶";
    if (playing) { if (playT >= winEnd) playT = winStart; lastFrame = performance.now(); raf = requestAnimationFrame(tick); }
    else if (raf) cancelAnimationFrame(raf);
  };

  connect();
}
init();
