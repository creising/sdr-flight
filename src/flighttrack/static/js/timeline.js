import { getBuckets } from "/static/js/api.js";

const DAY = 24 * 3600;
let el = null;

export function initTimeline() {
  el = document.createElement("div");
  el.id = "timeline";
  el.innerHTML = `
    <div class="tl-left cond"><div class="tl-title">LAST 24H</div><div class="tl-hint">live</div></div>
    <div class="tl-hist"><div class="bars"></div><div class="playhead"></div></div>
    <div class="now-pill cond">● NOW</div>`;
  document.getElementById("app").appendChild(el);
  renderLiveStrip();
  setInterval(renderLiveStrip, 30000);
}

export async function renderLiveStrip() {
  if (!el) return;
  const now = Date.now() / 1000;
  const buckets = await getBuckets(now - DAY, now, 96);
  const max = Math.max(1, ...buckets.map((b) => b.count));
  const bars = el.querySelector(".bars");
  bars.innerHTML = buckets.map((b, i) => {
    const h = (b.count / max) * 100;
    const live = i === buckets.length - 1 ? " live" : "";
    return `<div class="bar${live}" style="height:${h}%" title="${b.count}"></div>`;
  }).join("");
}
