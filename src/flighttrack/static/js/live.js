import { initTheme } from "/static/js/theme.js";
import { getConfig } from "/static/js/api.js";
import { state, set } from "/static/js/state.js";
import { initMap, renderAircraft, onSelect } from "/static/js/map.js";
import { connectLive } from "/static/js/socket.js";

(async function () {
  initTheme();
  const cfg = await getConfig();
  set({ receiver: cfg.receiver });
  initMap(cfg.receiver);
  onSelect((icao) => set({ selectedCallsign: icao }));
  connectLive((data) => {
    set({ contacts: data.aircraft });
    if (state.mode === "live") renderAircraft(data.aircraft);
  });
})();
