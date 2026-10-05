export const state = {
  mode: "live", playheadTime: null, playing: false, speed: 5, window: 3600,
  selectedCallsign: null, labelsOn: true, theme: "auto", sheetSnap: "peek",
  contacts: [], buckets: [], tracks: [], stats: null, receiver: null,
  flightDetail: null,   // { icao, airline, origin, destination, aircraft_type, route_known }
};
const subs = new Set();
export function subscribe(fn) { subs.add(fn); return () => subs.delete(fn); }
export function set(patch) { Object.assign(state, patch); for (const fn of subs) fn(state); }
