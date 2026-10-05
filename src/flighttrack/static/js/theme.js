const KEY = "ft-theme";
function resolve(pref) {
  if (pref === "auto")
    return matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  return pref;
}
export function setTheme(pref) {
  try { localStorage.setItem(KEY, pref); } catch (e) {}
  document.documentElement.setAttribute("data-theme", resolve(pref));
  document.documentElement.setAttribute("data-theme-pref", pref);
}
export function initTheme() {
  let pref = "auto";
  try { pref = localStorage.getItem(KEY) || "auto"; } catch (e) {}
  setTheme(pref);
  matchMedia("(prefers-color-scheme: light)").addEventListener("change", () => {
    let p = "auto";
    try { p = localStorage.getItem(KEY) || "auto"; } catch (e) {}
    if (p === "auto") setTheme("auto");
  });
}
