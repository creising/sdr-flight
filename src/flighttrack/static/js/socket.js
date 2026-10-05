import { state } from "/static/js/state.js";

export function connectLive(onFrame) {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  let ws;
  const open = () => {
    ws = new WebSocket(`${proto}://${location.host}/ws/live`);
    ws.onmessage = (e) => { if (state.mode === "live") onFrame(JSON.parse(e.data)); };
    ws.onclose = () => setTimeout(open, 2000);
  };
  open();
  return {
    isOpen: () => ws && ws.readyState === WebSocket.OPEN,
    reopen: () => { if (!ws || ws.readyState > 1) open(); },
  };
}
