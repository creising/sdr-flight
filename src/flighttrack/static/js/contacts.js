import { set, state } from "/static/js/state.js";
import { escapeHtml, altClass, isOverhead, lookupSubject, compass16, kmToNmi } from "/static/js/util.js";
import { openRaw } from "/static/js/rawinfo.js";

export function renderSidebar(container, onMode) {
  container.innerHTML = `
    <div class="sheet-bar">
      <button class="sheet-handle" aria-label="Expand or collapse panel"></button>
      <button class="sheet-close" aria-label="Close panel">✕</button>
    </div>
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
      <span class="cond">NEAREST FIRST</span><span class="cond num">NMI</span>
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
    const nmi = a.distance_km == null ? "—" : (kmToNmi(a.distance_km) < 10 ? kmToNmi(a.distance_km).toFixed(1) : Math.round(kmToNmi(a.distance_km)));
    const ft = a.alt_ft == null ? "—" : Math.round(a.alt_ft).toLocaleString();
    const elev = a.elevation_deg == null ? "—" : Math.round(a.elevation_deg);
    const oh = isOverhead(a.elevation_deg)
      ? `<span class="oh-tag cond" style="background:var(--alt-${cls})">OVERHEAD</span> ` : "";
    return `<li class="contact-row${isOverhead(a.elevation_deg) ? " overhead" : ""}" data-icao="${escapeHtml(a.icao)}">
      <span class="c-call">
        <svg class="row-chevron" width="12" height="12" viewBox="0 0 24 24" style="transform:rotate(${a.track_deg ?? 0}deg)">
          <polygon points="12,1 21,22 12,17 3,22" fill="var(--alt-${cls})"/></svg>
        <span class="cond c-name">${escapeHtml((a.callsign || a.icao || "").toUpperCase())}</span>
        <span class="c-sub">${oh}</span>
      </span>
      <span class="num c-km">${nmi}</span>
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

let lkKey = null;   // structural key of the currently-built card

function paintTrack(btn, icao) {
  const on = state.trackIcao === icao;
  btn.textContent = on ? "TRACKING" : "TRACK";
  btn.classList.toggle("active", on);
}

function renderLookup(subject, selected = false) {
  const el = document.getElementById("lookup");
  if (!el) return;
  if (!subject) {
    if (lkKey !== "empty") { el.innerHTML = `<div class="lookup-empty cond">NO CONTACTS</div>`; lkKey = "empty"; }
    return;
  }
  // Rebuild the card ONLY when the subject, selection, or its flight detail changes —
  // so the route/photo block (and its <img>) is created once, not on every telemetry tick.
  const detailKey = selected ? JSON.stringify(state.flightDetail || null) : "";
  const structKey = `${subject.icao}|${selected ? 1 : 0}|${detailKey}`;
  if (structKey !== lkKey) {
    lkKey = structKey;
    el.innerHTML = cardShell(subject, selected);
    el.querySelector(".lk-more")?.addEventListener("click",
      () => openRaw(subject.icao, subject.callsign || subject.icao));
    el.querySelector(".lk-close")?.addEventListener("click",
      () => set({ selectedCallsign: null }));
    const trackBtn = el.querySelector(".lk-track");
    if (trackBtn) {
      paintTrack(trackBtn, subject.icao);
      trackBtn.addEventListener("click", () => {
        set({ trackIcao: state.trackIcao === subject.icao ? null : subject.icao });
        paintTrack(trackBtn, subject.icao);
      });
    }
  }
  updateTelemetry(el, subject);   // in-place numeric/colour/gauge updates every tick
}

function cardShell(subject, selected) {
  const cls = altClass(subject.alt_ft) || "high";
  const label = selected ? "SELECTED" : "LOOK UP";
  return `
    <div class="lk-top"><span class="cond lbl">${label}</span>
      <span class="lk-top-right"><span class="cond lk-dir"></span>${
        selected ? `<button class="lk-close" aria-label="Close details" title="Back to list">×</button>` : ""
      }</span></div>
    <div class="lk-body">
      <div class="lk-call cond">${escapeHtml((subject.callsign || subject.icao || "").toUpperCase())}</div>
      <svg class="lk-gauge" width="72" height="72" viewBox="0 0 72 72">
        <path d="M68 66 A62 62 0 0 0 6 4" fill="none" stroke="var(--line-2)" stroke-width="2"/>
        <line x1="6" y1="66" x2="68" y2="66" stroke="var(--line-2)" stroke-width="2"/>
        <line class="gauge-needle" x1="6" y1="66" x2="68" y2="66" stroke="var(--alt-${cls})" stroke-width="2.5"/>
        <circle class="gauge-dot" cx="68" cy="66" r="3" fill="var(--alt-${cls})"/>
      </svg>
    </div>
    <div class="lk-grid">
      <div><span class="cond lbl">DIST</span><span class="num v v-dist"></span></div>
      <div><span class="cond lbl">ALT</span><span class="num v v-alt"></span></div>
      <div><span class="cond lbl">ELEV</span><span class="num v v-elev"></span></div>
    </div>
    <div class="lk-grid lk-grid2">
      <div><span class="cond lbl">SPD</span><span class="num v2 v-spd"></span></div>
      <div><span class="cond lbl">V·S</span><span class="num v2 v-vs"></span></div>
      <div><span class="cond lbl">SQUAWK</span><span class="num v2 v-sq"></span></div>
      <div><span class="cond lbl">SIGNAL</span><span class="v2 v-sig"></span></div>
    </div>
    ${selected ? `<button class="lk-track cond">TRACK</button>` +
      `<button class="lk-more cond">ⓘ&nbsp; RAW ADS-B DATA</button>${renderRoute(subject)}` : ""}`;
}

function updateTelemetry(el, s) {
  const color = `var(--alt-${altClass(s.alt_ft) || "high"})`;
  const elev = s.elevation_deg == null ? 0 : Math.round(s.elevation_deg);
  const dir = s.bearing_deg == null ? "" : compass16(s.bearing_deg) + " · ";
  const nmi = s.distance_km == null ? "—" : kmToNmi(s.distance_km).toFixed(1);
  const ft = s.alt_ft == null ? "—" : Math.round(s.alt_ft).toLocaleString();
  const q = (sel) => el.querySelector(sel);
  const dirEl = q(".lk-dir"); if (dirEl) dirEl.textContent = `${dir}${elev}° UP`;
  for (const cl of [".gauge-needle", ".gauge-dot"]) {
    const g = q(cl);
    if (g) {
      g.setAttribute("transform", `rotate(${-elev} 6 66)`);
      g.setAttribute(cl === ".gauge-dot" ? "fill" : "stroke", color);
    }
  }
  const trackBtn = q(".lk-track");
  if (trackBtn) paintTrack(trackBtn, s.icao);
  const vd = q(".v-dist"), va = q(".v-alt"), ve = q(".v-elev");
  if (vd) vd.innerHTML = `${nmi}<i>nmi</i>`;
  if (va) { va.innerHTML = `${ft}<i>ft</i>`; va.style.color = color; }
  if (ve) ve.innerHTML = `${elev}<i>°</i>`;

  // second row: speed / vertical rate / squawk / signal
  const spd = q(".v-spd");
  if (spd) spd.innerHTML = s.ground_speed_kt == null ? "—" : `${Math.round(s.ground_speed_kt)}<i>kt</i>`;
  const vs = q(".v-vs");
  if (vs) {
    const vr = s.baro_rate;
    if (vr == null) { vs.innerHTML = "—"; vs.className = "num v2 v-vs"; }
    else {
      const arrow = vr > 50 ? "↑" : vr < -50 ? "↓" : "→";
      vs.innerHTML = `${arrow} ${Math.abs(Math.round(vr)).toLocaleString()}<i>fpm</i>`;
      vs.className = "num v2 v-vs " + (vr > 50 ? "climb" : vr < -50 ? "descend" : "");
    }
  }
  const sq = q(".v-sq");
  if (sq) {
    const code = s.squawk || "—";
    const emg = { "7500": "HIJACK", "7600": "RADIO FAIL", "7700": "EMERGENCY" }[s.squawk];
    sq.textContent = emg ? `${code} ⚠` : code;
    sq.className = "num v2 v-sq" + (emg ? " sq-emergency" : "");
    sq.title = emg || "";
  }
  const sig = q(".v-sig");
  if (sig) {
    const r = s.rssi;
    const pct = r == null ? 0 : Math.max(4, Math.min(100, ((r + 35) / 32) * 100));
    sig.innerHTML = `<span class="sigbar"><i style="width:${pct.toFixed(0)}%"></i></span>` +
      `<span class="signum num">${r == null ? "—" : r.toFixed(0) + " dBFS"}</span>`;
  }
}

function renderRoute(subject) {
  const d = state.flightDetail;
  if (!d || d.icao !== subject.icao) return `<div class="lk-route loading cond">LOOKING UP…</div>`;
  const bits = [];

  // Route
  if (d.route_known && d.origin && d.destination) {
    bits.push(`<div class="rt-leg"><b>${escapeHtml(d.origin.code || "?")}</b> → <b>${escapeHtml(d.destination.code || "?")}</b></div>`);
    const cities = [];
    if (d.origin.city) cities.push(escapeHtml(d.origin.city));
    if (d.destination.city) cities.push(escapeHtml(d.destination.city));
    if (cities.length) bits.push(`<div class="rt-cities">${cities.join(" → ")}</div>`);
  } else {
    bits.push(`<div class="rt-unknown cond">ROUTE UNKNOWN</div>`);
  }

  // Airline / type / registration
  const meta = [];
  if (d.airline) meta.push(escapeHtml(d.airline));
  if (d.aircraft_type) meta.push(escapeHtml(d.aircraft_type));
  if (d.registration) meta.push(escapeHtml(d.registration));
  if (meta.length) bits.push(`<div class="rt-meta">${meta.join(" · ")}</div>`);

  // Aircraft make/model/year (FAA)
  const ac = [[d.make, d.model].filter(Boolean).map(escapeHtml).join(" "), d.year ? escapeHtml(d.year) : ""]
    .filter(Boolean).join(" · ");
  if (ac) bits.push(`<div class="rt-ac">${ac}</div>`);

  // Photo (planespotters — attribution required)
  if (d.photo && d.photo.thumbnail) {
    const credit = d.photo.credit ? `© ${escapeHtml(d.photo.credit)}` : "";
    bits.push(`<a class="rt-photo" href="${escapeHtml(d.photo.link || "#")}" target="_blank" rel="noopener">` +
      `<img src="${escapeHtml(d.photo.thumbnail)}" alt="aircraft photo" loading="lazy">` +
      `<span class="rt-credit">${credit}${credit ? " · " : ""}planespotters.net</span></a>`);
  }

  return `<div class="lk-route">${bits.join("")}</div>`;
}
