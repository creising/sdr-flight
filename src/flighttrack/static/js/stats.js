import { getSummary, getPerHour, getAirlines } from "/static/js/api.js";
import { escapeHtml } from "/static/js/util.js";
import { initTheme } from "/static/js/theme.js";

initTheme();

function headlineTile(label, value, sub) {
  return `<div class="headline-tile">
    <div class="ht-label cond">${label}</div>
    <div class="ht-value num">${value}</div>
    <div class="ht-sub">${sub || ""}</div></div>`;
}
function recordTile(label, value, sub) {
  return `<div class="record-tile">
    <div class="rt-label cond">${label}</div>
    <div class="rt-value num">${value}</div>
    <div class="rt-sub">${sub || ""}</div></div>`;
}

async function renderSummary() {
  const s = await getSummary();
  const closest = s.closest ? `${escapeHtml(s.closest.callsign || s.closest.icao)} · ${s.closest.km.toFixed(1)} km` : "—";
  const farthest = s.farthest ? `${escapeHtml(s.farthest.callsign || s.farthest.icao)} · ${s.farthest.km.toFixed(1)} km` : "—";
  const high = s.highest_alt_ft != null ? `${Math.round(s.highest_alt_ft).toLocaleString()} ft` : "—";
  document.getElementById("headline").innerHTML =
    headlineTile("Seen today", s.sessions_today, "contacts since midnight") +
    headlineTile("Seen all-time", s.sessions_total, `${s.unique_total} unique aircraft`);
  document.getElementById("records").innerHTML =
    recordTile("Closest pass", s.closest ? `${s.closest.km.toFixed(1)} km` : "—", s.closest ? escapeHtml(s.closest.callsign || s.closest.icao) : "") +
    recordTile("Farthest", s.farthest ? `${Math.round(s.farthest.km)} km` : "—", s.farthest ? escapeHtml(s.farthest.callsign || s.farthest.icao) : "") +
    recordTile("Highest", high, "") +
    recordTile("Busiest hour", s.busiest_hour || "—", "");
}

// Radial 24-hour clock: 24 bars rotated hour*15deg around centre (00 at top, clockwise).
async function renderRadial() {
  const data = await getPerHour();                 // 24 buckets {label "HH:00", count}
  const byHour = new Array(24).fill(0);
  let busiest = -1, busiestCount = -1;
  for (const b of data) {
    const h = parseInt(b.label, 10);
    if (h >= 0 && h < 24) { byHour[h] = b.count; if (b.count > busiestCount) { busiestCount = b.count; busiest = h; } }
  }
  const max = Math.max(1, ...byHour);
  const R = 220, cx = R, cy = R, inner = 86, maxLen = 118, w = 14;
  const nowH = new Date().getHours();
  let bars = "";
  for (let h = 0; h < 24; h++) {
    const len = (byHour[h] / max) * maxLen;
    const color = h === busiest && busiestCount > 0 ? "var(--alt-mid)" : "var(--alt-high)";
    const y = cy - inner - len;
    bars += `<rect x="${cx - w / 2}" y="${y}" width="${w}" height="${Math.max(0, len)}" rx="3" ` +
            `fill="${color}" transform="rotate(${h * 15} ${cx} ${cy})"><title>${h}:00 — ${byHour[h]}</title></rect>`;
  }
  const needle = `<line x1="${cx}" y1="${cy - inner + 6}" x2="${cx}" y2="${cy - inner - maxLen - 6}" ` +
    `stroke="var(--live)" stroke-width="2" transform="rotate(${nowH * 15} ${cx} ${cy})"/>`;
  const labels = [0, 6, 12, 18].map((h) => {
    const a = (h * 15 - 90) * Math.PI / 180, rr = inner + maxLen + 16;
    return `<text x="${cx + rr * Math.cos(a)}" y="${cy + rr * Math.sin(a) + 4}" text-anchor="middle" ` +
      `font-size="12" fill="var(--dim)">${String(h).padStart(2, "0")}</text>`;
  }).join("");
  const center = `<text x="${cx}" y="${cy - 10}" text-anchor="middle" font-size="12" fill="var(--muted)" letter-spacing="2">PEAK</text>` +
    `<text x="${cx}" y="${cy + 22}" text-anchor="middle" font-size="30" fill="var(--alt-mid)" font-weight="600">${busiest >= 0 && busiestCount > 0 ? busiest + ":00" : "—"}</text>`;
  document.getElementById("radial").innerHTML =
    `<svg viewBox="0 0 ${2 * R} ${2 * R}" width="100%" style="max-width:${2 * R}px">${bars}${needle}${labels}${center}</svg>`;
}

async function renderAirlines() {
  const rows = await getAirlines();
  const max = Math.max(1, ...rows.map((r) => r.count));
  document.getElementById("airlines").innerHTML = rows.map((r) => {
    const w = (r.count / max) * 100;
    const ga = r.airline === "Private / GA";
    return `<div class="airline-row">
      <span class="al-code mono">${ga ? "—" : escapeHtml(r.airline)}</span>
      <span class="al-name">${escapeHtml(r.airline)}</span>
      <span class="al-bar"><i style="width:${w}%;background:${ga ? "var(--dim)" : "var(--alt-high)"}"></i></span>
      <span class="al-count num">${r.count}</span>
      <span class="al-share num">${Math.round(r.share * 100)}%</span>
    </div>`;
  }).join("") || `<div class="al-empty">No airlines logged yet</div>`;
}

renderSummary();
renderRadial();
renderAirlines();
