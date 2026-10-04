let map, youMarker;
const markers = new Map(); // icao -> L.marker

function altColor(ft) {
  if (ft == null) return "#9aa7b2";
  if (ft < 10000) return "#ff5d5d";
  if (ft < 25000) return "#ffb24d";
  return "#5dd0ff";
}

function planeIcon(a) {
  const rot = a.track_deg ?? 0;
  return L.divIcon({
    className: "",
    html: `<div class="plane" style="transform: rotate(${rot}deg); color:${altColor(a.alt_ft)}">✈</div>`,
    iconSize: [20, 20], iconAnchor: [10, 10],
  });
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

function update(data) {
  const seen = new Set();
  for (const a of data.aircraft) {
    seen.add(a.icao);
    let m = markers.get(a.icao);
    if (!m) { m = L.marker([a.lat, a.lon], { icon: planeIcon(a) }).addTo(map); markers.set(a.icao, m); }
    else { m.setLatLng([a.lat, a.lon]); m.setIcon(planeIcon(a)); }
    m.bindTooltip(a.callsign || a.icao);
  }
  for (const [icao, m] of markers) if (!seen.has(icao)) { map.removeLayer(m); markers.delete(icao); }
  renderContacts(data.aircraft);
  document.getElementById("status").textContent =
    `${data.aircraft.length} aircraft · live`;
}

async function init() {
  const cfg = await (await fetch("/api/config")).json();
  const { lat, lon } = cfg.receiver;
  map = L.map("map").setView([lat, lon], 9);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    { attribution: "© OpenStreetMap", maxZoom: 18 }).addTo(map);
  youMarker = L.circleMarker([lat, lon], { radius: 6, color: "#4de6a1", fillOpacity: 1 })
    .addTo(map).bindTooltip("You");

  const proto = location.protocol === "https:" ? "wss" : "ws";
  function connect() {
    const ws = new WebSocket(`${proto}://${location.host}/ws/live`);
    ws.onmessage = (e) => update(JSON.parse(e.data));
    ws.onclose = () => {
      document.getElementById("status").textContent = "reconnecting…";
      setTimeout(connect, 2000);
    };
  }
  connect();
}
init();
