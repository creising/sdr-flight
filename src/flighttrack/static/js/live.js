import { initTheme, cycleTheme } from "/static/js/theme.js";
import { getConfig } from "/static/js/api.js";
import { state, set } from "/static/js/state.js";
import { initMap, renderAircraft, onSelect } from "/static/js/map.js";
import { connectLive } from "/static/js/socket.js";
import { renderSidebar, renderContacts } from "/static/js/contacts.js";
import { initTimeline, setModeFromSidebar } from "/static/js/timeline.js";

let latestLive = [];

(async function () {
  initTheme();
  const sidebar = document.getElementById("sidebar");
  renderSidebar(sidebar, setModeFromSidebar);
  document.querySelector(".theme-toggle").addEventListener("click", () => cycleTheme());
  document.querySelector(".sheet-handle").addEventListener("click", () => sidebar.classList.toggle("expanded"));
  const cfg = await getConfig();
  set({ receiver: cfg.receiver });
  initMap(cfg.receiver);
  initTimeline({ onLiveResume: () => { if (latestLive.length) { renderAircraft(latestLive); renderContacts(latestLive); } } });
  onSelect((icao) => set({ selectedCallsign: icao }));
  connectLive((data) => {
    latestLive = data.aircraft;
    set({ contacts: data.aircraft });
    if (state.mode === "live") {
      renderAircraft(data.aircraft);
      renderContacts(data.aircraft);
      document.getElementById("status").textContent = `${data.aircraft.length} aircraft · live`;
      const tc = document.getElementById("tb-count");
      if (tc) tc.textContent = `${data.aircraft.length} aircraft`;
    }
  });
})();
