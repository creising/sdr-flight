const j = async (u) => (await fetch(u)).json();
export const getConfig = () => j("/api/config");
export const getSummary = () => j("/api/stats/summary");
export const getPerHour = () => j("/api/stats/per-hour");
export const getAirlines = () => j("/api/stats/airlines");
export const getBuckets = (from, to, n) => j(`/api/stats/buckets?from=${from}&to=${to}&n=${n}`);
export const getHistory = (from, to) => j(`/api/history?from=${from}&to=${to}`);
