import { initTheme } from "/static/js/theme.js";
import { getConfig } from "/static/js/api.js";
import { state, set } from "/static/js/state.js";
import { initMap, renderAircraft, onSelect } from "/static/js/map.js";
import { connectLive } from "/static/js/socket.js";
import { renderSidebar, renderContacts } from "/static/js/contacts.js";
import { initTimeline } from "/static/js/timeline.js";

(async function () {
  initTheme();
  renderSidebar(document.getElementById("sidebar"));
  const cfg = await getConfig();
  set({ receiver: cfg.receiver });
  initMap(cfg.receiver);
  initTimeline();
  onSelect((icao) => set({ selectedCallsign: icao }));
  connectLive((data) => {
    set({ contacts: data.aircraft });
    if (state.mode === "live") {
      renderAircraft(data.aircraft);
      renderContacts(data.aircraft);
      const n = data.aircraft.length;
      document.getElementById("status").textContent = `${n} aircraft · live`;
    }
  });
})();
