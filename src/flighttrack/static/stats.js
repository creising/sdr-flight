const ACCENT = "#5dd0ff";
const INK_MUTED = "#8aa0b4";

function tile(label, value, sub) {
  return `<div class="tile"><div class="tval">${value}</div>` +
         `<div class="tlabel">${label}</div>` +
         (sub ? `<div class="tsub">${sub}</div>` : "") + `</div>`;
}

async function loadTiles() {
  const s = await (await fetch("/api/stats/summary")).json();
  const closest = s.closest ? `${s.closest.callsign || s.closest.icao} · ${s.closest.km.toFixed(1)} km` : "—";
  const farthest = s.farthest ? `${s.farthest.callsign || s.farthest.icao} · ${s.farthest.km.toFixed(1)} km` : "—";
  const high = s.highest_alt_ft != null ? `${Math.round(s.highest_alt_ft).toLocaleString()} ft` : "—";
  document.getElementById("tiles").innerHTML =
    tile("Seen today", s.sessions_today) +
    tile("Seen all-time", s.sessions_total, `${s.unique_total} unique`) +
    tile("Closest pass", closest) +
    tile("Farthest", farthest) +
    tile("Highest", high) +
    tile("Busiest hour", s.busiest_hour || "—");
}

// Single-series magnitude bar chart as inline SVG (dataviz: one hue, labels, hover).
function barChart(el, rows, labelKey, valueKey) {
  const W = el.clientWidth || 600, H = 220, padL = 32, padB = 28, padT = 8;
  const max = Math.max(1, ...rows.map(r => r[valueKey]));
  const n = rows.length || 1;
  const bw = (W - padL) / n;
  const bars = rows.map((r, i) => {
    const h = (H - padB - padT) * (r[valueKey] / max);
    const x = padL + i * bw + 2, y = H - padB - h;
    const w = Math.max(1, bw - 4);
    return `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="4" fill="${ACCENT}">` +
           `<title>${r[labelKey]}: ${r[valueKey]}</title></rect>` +
           (r[valueKey] > 0 ? `<text x="${x + w / 2}" y="${y - 4}" text-anchor="middle" ` +
             `font-size="10" fill="${INK_MUTED}">${r[valueKey]}</text>` : "") +
           `<text x="${x + w / 2}" y="${H - padB + 14}" text-anchor="middle" ` +
             `font-size="9" fill="${INK_MUTED}">${r[labelKey]}</text>`;
  }).join("");
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" role="img">${bars}</svg>`;
}

async function loadCharts() {
  const perhour = await (await fetch("/api/stats/per-hour")).json();
  barChart(document.getElementById("perhour"), perhour, "label", "count");
  const airlines = await (await fetch("/api/stats/airlines")).json();
  barChart(document.getElementById("airlines"), airlines, "airline", "count");
}

loadTiles();
loadCharts();
