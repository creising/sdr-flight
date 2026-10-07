export function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
export function elevationDeg(altFt, groundKm) {
  if (altFt == null || groundKm == null || groundKm <= 0) return 90;
  return (Math.atan((altFt * 0.0003048) / groundKm) * 180) / Math.PI;
}
// Distance is stored and transmitted in km; the UI displays nautical miles.
export const NMI_PER_KM = 0.5399568;
export function kmToNmi(km) { return km == null ? null : km * NMI_PER_KM; }
// Destination point [lat, lon] reached from (lat, lon) travelling distNmi along
// a great circle on bearing bearingDeg. Standard spherical "direct" formula.
export function destPoint(lat, lon, bearingDeg, distNmi) {
  const R = 3440.065;                       // mean Earth radius in nautical miles
  const d = distNmi / R;                    // angular distance (radians)
  const br = (bearingDeg * Math.PI) / 180;
  const la1 = (lat * Math.PI) / 180;
  const lo1 = (lon * Math.PI) / 180;
  const la2 = Math.asin(Math.sin(la1) * Math.cos(d) + Math.cos(la1) * Math.sin(d) * Math.cos(br));
  const lo2 = lo1 + Math.atan2(
    Math.sin(br) * Math.sin(d) * Math.cos(la1),
    Math.cos(d) - Math.sin(la1) * Math.sin(la2),
  );
  return [(la2 * 180) / Math.PI, (((lo2 * 180) / Math.PI + 540) % 360) - 180];
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
