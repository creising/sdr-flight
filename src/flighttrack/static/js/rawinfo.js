import { escapeHtml } from "/static/js/util.js";

let pollTimer = null;
let escHandler = null;

function fmt(v) {
  if (v === null || v === undefined) return "—";
  if (Array.isArray(v)) return v.length ? v.join(", ") : "[]";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

function renderRaw(d) {
  const keys = Object.keys(d).sort();
  if (!keys.length) {
    return `<div class="raw-empty cond">NO LIVE DATA — aircraft out of range?</div>`;
  }
  return `<dl class="raw-list">` + keys.map((k) =>
    `<div class="raw-row"><dt class="mono">${escapeHtml(k)}</dt>` +
    `<dd class="mono">${escapeHtml(fmt(d[k]))}</dd></div>`).join("") + `</dl>`;
}

export function openRaw(hex, label) {
  let dlg = document.getElementById("rawdialog");
  if (!dlg) { dlg = document.createElement("div"); dlg.id = "rawdialog"; document.body.appendChild(dlg); }
  dlg.innerHTML = `
    <div class="raw-backdrop"></div>
    <div class="raw-panel" role="dialog" aria-modal="true">
      <div class="raw-head">
        <span class="cond raw-title">${escapeHtml((label || hex).toUpperCase())} · RAW ADS-B</span>
        <button class="raw-close" aria-label="Close">✕</button>
      </div>
      <div class="raw-sub">everything decoded from the radio · live</div>
      <div class="raw-body" id="raw-body"><div class="raw-empty cond">LOADING…</div></div>
    </div>`;
  dlg.style.display = "block";

  const close = () => {
    dlg.style.display = "none";
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    if (escHandler) { document.removeEventListener("keydown", escHandler); escHandler = null; }
  };
  dlg.querySelector(".raw-close").onclick = close;
  dlg.querySelector(".raw-backdrop").onclick = close;
  escHandler = (e) => { if (e.key === "Escape") close(); };
  document.addEventListener("keydown", escHandler);

  async function load() {
    try {
      const d = await (await fetch(`/api/aircraft/${encodeURIComponent(hex)}`)).json();
      const body = document.getElementById("raw-body");
      if (body) body.innerHTML = renderRaw(d);
    } catch (e) { /* keep last values */ }
  }
  load();
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(load, 1000);   // live while open
}
