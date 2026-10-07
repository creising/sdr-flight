import { initTheme, cycleTheme } from "/static/js/theme.js";
import { getConfig, getFlight } from "/static/js/api.js";
import { state, set, subscribe } from "/static/js/state.js";
import { initMap, renderAircraft, onSelect, panTo, recenterMap } from "/static/js/map.js";
import { connectLive } from "/static/js/socket.js";
import { renderSidebar, renderContacts } from "/static/js/contacts.js";
import { initTimeline, setModeFromSidebar } from "/static/js/timeline.js";

let latestLive = [];

// Mobile bottom-sheet handle: tap toggles, drag down collapses / drag up expands.
// Pointer capture + touch-action:none (CSS) keep the gesture off the map behind it.
function initSheetHandle(handle, sidebar) {
  if (!handle) return;
  const THRESH = 24;            // px of travel that counts as a swipe vs a tap
  let startY = null, moved = false;
  handle.addEventListener("pointerdown", (e) => {
    startY = e.clientY; moved = false;
    try { handle.setPointerCapture(e.pointerId); } catch { /* older browsers */ }
  });
  handle.addEventListener("pointermove", (e) => {
    if (startY == null) return;
    e.preventDefault();         // don't let the swipe scroll the page or pan the map
    if (Math.abs(e.clientY - startY) > 6) moved = true;
  });
  handle.addEventListener("pointerup", (e) => {
    if (startY == null) return;
    const dy = e.clientY - startY;
    startY = null;
    if (!moved) { sidebar.classList.toggle("expanded"); return; }   // tap
    if (dy > THRESH) sidebar.classList.remove("expanded");          // swipe down → dismiss
    else if (dy < -THRESH) sidebar.classList.add("expanded");       // swipe up → expand
  });
  handle.addEventListener("pointercancel", () => { startY = null; });
}

(async function () {
  initTheme();
  const sidebar = document.getElementById("sidebar");
  renderSidebar(sidebar, setModeFromSidebar);
  document.querySelector(".theme-toggle").addEventListener("click", () => cycleTheme());
  initSheetHandle(document.querySelector(".sheet-handle"), sidebar);
  document.querySelector(".sheet-close")?.addEventListener("click", () => sidebar.classList.remove("expanded"));
  document.getElementById("recenter")?.addEventListener("click", () => recenterMap());
  const cfg = await getConfig();
  set({ receiver: cfg.receiver });
  initMap(cfg.receiver);
  const opts = () => ({ selected: state.selectedCallsign, labelsOn: state.labelsOn, track: state.trackIcao });
  initTimeline({ onLiveResume: () => { if (latestLive.length) { renderAircraft(latestLive, opts()); renderContacts(latestLive); } } });
  onSelect((icao) =>
    set({ selectedCallsign: state.selectedCallsign === icao ? null : icao }));

  // React to selection from either a marker click or a contacts-row click.
  let lastSelected = null;
  let lastTrack = null;
  subscribe((s) => {
    if (s.trackIcao !== lastTrack) {
      lastTrack = s.trackIcao;
      if (state.mode === "live") renderAircraft(latestLive, opts());
    }
    if (s.selectedCallsign !== lastSelected) {
      lastSelected = s.selectedCallsign;
      set({ flightDetail: null });
      if (s.selectedCallsign) {
        // Bring the details into view — on the mobile bottom-sheet the collapsed
        // strip hides them, so a marker/row tap must expand the sheet.
        sidebar.classList.add("expanded");
        panTo(s.selectedCallsign);
        const c = latestLive.find((a) => a.icao === s.selectedCallsign)
          || (state.contacts || []).find((a) => a.icao === s.selectedCallsign);
        if (c) {
          getFlight(c.callsign || c.icao, c.icao)
            .then((d) => {
              if (state.selectedCallsign === c.icao) {
                set({ flightDetail: { icao: c.icao, ...d } });
                if (state.mode === "live") renderContacts(latestLive);
              }
            })
            .catch(() => {});
        }
      } else {
        // Details dismissed — collapse the mobile sheet so the map is visible again.
        sidebar.classList.remove("expanded");
      }
      if (state.mode === "live") { renderAircraft(latestLive, opts()); renderContacts(latestLive); }
    }
  });

  connectLive((data) => {
    latestLive = data.aircraft;
    set({ contacts: data.aircraft });
    if (state.mode === "live") {
      renderAircraft(data.aircraft, opts());
      renderContacts(data.aircraft);
      document.getElementById("status").textContent = `${data.aircraft.length} aircraft · live`;
      const tc = document.getElementById("tb-count");
      if (tc) tc.textContent = `${data.aircraft.length} aircraft`;
    }
  });
})();
