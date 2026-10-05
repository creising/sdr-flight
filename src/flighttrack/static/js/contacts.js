import { set } from "/static/js/state.js";

export function renderSidebar(container) {
  container.innerHTML = `
    <header class="sb-header">
      <span class="wordmark cond">OVERHEAD</span>
      <a href="/stats" class="statslink">Stats →</a>
    </header>
    <div class="mode-switch" role="tablist">
      <button class="mode-seg active" data-mode="live"><span class="live-dot"></span>Live</button>
      <button class="mode-seg" data-mode="replay">Replay</button>
    </div>
    <div id="status" class="status">connecting…</div>
    <div id="lookup" class="lookup-card"></div>
    <div class="col-head">
      <span class="cond">NEAREST FIRST</span><span class="cond num">KM</span>
      <span class="cond num">FT</span><span class="cond num">ELEV</span>
    </div>
    <ul id="contacts" class="contacts"></ul>
    <footer class="legend">
      <span><i class="sw" style="background:var(--alt-low)"></i>&lt;10k ft</span>
      <span><i class="sw" style="background:var(--alt-mid)"></i>&lt;25k</span>
      <span><i class="sw" style="background:var(--alt-high)"></i>≥25k</span>
    </footer>`;
  container.querySelectorAll(".mode-seg").forEach((b) => {
    b.addEventListener("click", () => setMode(container, b.dataset.mode));
  });
}

export function setMode(container, mode) {
  set({ mode });
  container.querySelectorAll(".mode-seg").forEach((b) =>
    b.classList.toggle("active", b.dataset.mode === mode));
  container.setAttribute("data-mode", mode);
  const app = document.getElementById("app");
  if (app) app.setAttribute("data-mode", mode);
}
