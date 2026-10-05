export function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
export function elevationDeg(altFt, groundKm) {
  if (altFt == null || groundKm == null || groundKm <= 0) return 90;
  return (Math.atan((altFt * 0.0003048) / groundKm) * 180) / Math.PI;
}
export function isOverhead(elevDeg) { return elevDeg != null && elevDeg >= 40; }
export function lookupSubject(contacts) {
  let best = null;
  for (const c of contacts) {
    if (c.lat == null && c.elevation_deg == null) continue;
    if (!best || (c.elevation_deg ?? -1) > (best.elevation_deg ?? -1)) best = c;
  }
  return best;
}
const DIRS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
              "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];
export function compass16(bearingDeg) {
  return DIRS[Math.round((((bearingDeg % 360) + 360) % 360) / 22.5) % 16];
}
export function flightLevel(altFt) {
  return String(Math.round((altFt ?? 0) / 100)).padStart(3, "0");
}
export function altClass(altFt) {
  if (altFt == null) return null;
  if (altFt < 10000) return "low";
  if (altFt < 25000) return "mid";
  return "high";
}
export function altTrend(prevAltFt, altFt) {
  if (prevAltFt == null || altFt == null) return "flat";
  if (altFt > prevAltFt + 50) return "up";
  if (altFt < prevAltFt - 50) return "down";
  return "flat";
}
export function bucketIndex(ts, start, end, n) {
  if (n <= 0 || end <= start || ts < start || ts >= end) return -1;
  return Math.floor((ts - start) / ((end - start) / n));
}
