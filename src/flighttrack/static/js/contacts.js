import { set, state } from "/static/js/state.js";
import { escapeHtml, altClass, isOverhead, lookupSubject, compass16 } from "/static/js/util.js";

export function renderSidebar(container, onMode) {
  container.innerHTML = `
    <button class="sheet-handle" aria-label="expand"></button>
    <header class="sb-header">
      <span class="wordmark cond">OVERHEAD</span>
      <span class="sb-head-right">
        <button class="theme-toggle" title="Theme" aria-label="Toggle theme">◐</button>
        <a href="/stats" class="statslink">Stats →</a>
      </span>
    </header>
    <div class="mode-switch" role="tablist">
      <button class="mode-seg active" data-mode="live"><span class="live-dot"></span>Live</button>
      <button class="mode-seg" data-mode="replay">Replay</button>
    </div>
    <div id="status" class="status">connecting…</div>
    <div id="lookup" class="lookup-card"></div>
    <div class="col-head">
      <span class="cond">NEAREST FIRST</span><span class="cond num">KM</span>
      <span class="cond num">FT</span><span class="cond num">ELEV</span>
    </div>
    <ul id="contacts" class="contacts"></ul>
    <footer class="legend">
      <span><i class="sw" style="background:var(--alt-low)"></i>&lt;10k ft</span>
      <span><i class="sw" style="background:var(--alt-mid)"></i>&lt;25k</span>
      <span><i class="sw" style="background:var(--alt-high)"></i>≥25k</span>
    </footer>`;
  container.querySelectorAll(".mode-seg").forEach((b) => {
    b.addEventListener("click", () => onMode && onMode(b.dataset.mode));
  });
}

export function renderContacts(contacts) {
  const sel = state.selectedCallsign
    ? contacts.find((c) => c.icao === state.selectedCallsign) : null;
  renderLookup(sel || lookupSubject(contacts), !!sel);
  const ul = document.getElementById("contacts");
  if (!ul) return;
  const rows = contacts.filter((c) => c.lat != null)
    .sort((a, b) => (a.distance_km ?? 1e9) - (b.distance_km ?? 1e9));
  ul.innerHTML = rows.map((a) => {
    const cls = altClass(a.alt_ft) || "high";
    const km = a.distance_km == null ? "—" : (a.distance_km < 10 ? a.distance_km.toFixed(1) : Math.round(a.distance_km));
    const ft = a.alt_ft == null ? "—" : Math.round(a.alt_ft).toLocaleString();
    const elev = a.elevation_deg == null ? "—" : Math.round(a.elevation_deg);
    const oh = isOverhead(a.elevation_deg)
      ? `<span class="oh-tag cond" style="background:var(--alt-${cls})">OVERHEAD</span> ` : "";
    return `<li class="contact-row${isOverhead(a.elevation_deg) ? " overhead" : ""}" data-icao="${escapeHtml(a.icao)}">
      <span class="c-call">
        <svg class="row-chevron" width="12" height="12" viewBox="0 0 24 24" style="transform:rotate(${a.track_deg ?? 0}deg)">
          <polygon points="12,1 21,22 12,17 3,22" fill="var(--alt-${cls})"/></svg>
        <span class="cond c-name">${escapeHtml(a.callsign || a.icao)}</span>
        <span class="c-sub">${oh}</span>
      </span>
      <span class="num c-km">${km}</span>
      <span class="num c-ft" style="color:var(--alt-${cls})">${ft}</span>
      <span class="num c-elev">${elev}°</span>
    </li>`;
  }).join("");
  ul.querySelectorAll(".contact-row").forEach((li) =>
    li.addEventListener("click", () => {
      const icao = li.dataset.icao;
      set({ selectedCallsign: state.selectedCallsign === icao ? null : icao });
    }));
}

function renderLookup(subject, selected = false) {
  const el = document.getElementById("lookup");
  if (!el) return;
  if (!subject) { el.innerHTML = `<div class="lookup-empty cond">NO CONTACTS</div>`; return; }
  const cls = altClass(subject.alt_ft) || "high";
  const elev = subject.elevation_deg == null ? 0 : Math.round(subject.elevation_deg);
  const dir = subject.bearing_deg == null ? "" : compass16(subject.bearing_deg) + " · ";
  const km = subject.distance_km == null ? "—" : subject.distance_km.toFixed(1);
  const ft = subject.alt_ft == null ? "—" : Math.round(subject.alt_ft).toLocaleString();
  const label = selected ? "SELECTED" : "LOOK UP";
  el.innerHTML = `
    <div class="lk-top"><span class="cond lbl">${label}</span>
      <span class="cond lk-dir">${dir}${elev}° UP</span></div>
    <div class="lk-body">
      <div class="lk-call cond">${escapeHtml(subject.callsign || subject.icao)}</div>
      <svg class="lk-gauge" width="72" height="72" viewBox="0 0 72 72">
        <path d="M68 66 A62 62 0 0 0 6 4" fill="none" stroke="var(--line-2)" stroke-width="2"/>
        <line x1="6" y1="66" x2="68" y2="66" stroke="var(--line-2)" stroke-width="2"/>
        <line x1="6" y1="66" x2="68" y2="66" stroke="var(--alt-${cls})" stroke-width="2.5"
          transform="rotate(${-elev} 6 66)"/>
        <circle cx="68" cy="66" r="3" fill="var(--alt-${cls})" transform="rotate(${-elev} 6 66)"/>
      </svg>
    </div>
    <div class="lk-grid">
      <div><span class="cond lbl">DIST</span><span class="num v">${km}<i>km</i></span></div>
      <div><span class="cond lbl">ALT</span><span class="num v" style="color:var(--alt-${cls})">${ft}<i>ft</i></span></div>
      <div><span class="cond lbl">ELEV</span><span class="num v">${elev}<i>°</i></span></div>
    </div>
    ${selected ? renderRoute(subject) : ""}`;
}

function renderRoute(subject) {
  const d = state.flightDetail;
  if (!d || d.icao !== subject.icao) return `<div class="lk-route loading cond">LOOKING UP ROUTE…</div>`;
  const parts = [];
  if (d.route_known && d.origin && d.destination) {
    parts.push(`<span class="rt-leg"><b>${escapeHtml(d.origin.code || "?")}</b> → <b>${escapeHtml(d.destination.code || "?")}</b></span>`);
    const sub = [];
    if (d.origin.city) sub.push(escapeHtml(d.origin.city));
    if (d.destination.city) sub.push(escapeHtml(d.destination.city));
    const meta = [];
    if (d.airline) meta.push(escapeHtml(d.airline));
    if (d.aircraft_type) meta.push(escapeHtml(d.aircraft_type));
    return `<div class="lk-route">${parts[0]}
      <div class="rt-cities">${sub.join(" → ")}</div>
      ${meta.length ? `<div class="rt-meta">${meta.join(" · ")}</div>` : ""}</div>`;
  }
  const meta = [];
  if (d.aircraft_type) meta.push(escapeHtml(d.aircraft_type));
  if (d.registration) meta.push(escapeHtml(d.registration));
  return `<div class="lk-route unknown cond">ROUTE UNKNOWN${meta.length ? ` · ${meta.join(" · ")}` : ""}</div>`;
}
