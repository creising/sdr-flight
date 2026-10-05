import { getBuckets, getHistory } from "/static/js/api.js";
import { state, set } from "/static/js/state.js";
import { renderReplay, clearAircraft } from "/static/js/map.js";

const DAY = 24 * 3600;
let el = null, liveTimer = null, raf = null, lastFrame = 0;
let winStart = 0, winEnd = 0;         // replay window
let onLiveResume = null;

export function initTimeline(opts = {}) {
  onLiveResume = opts.onLiveResume || null;
  el = document.createElement("div");
  el.id = "timeline";
  document.getElementById("app").appendChild(el);
  renderLivePanel();
}

const reducedMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

/* ---------- Live ---------- */
export function renderLivePanel() {
  if (liveTimer) clearInterval(liveTimer);
  el.classList.remove("replay");
  el.innerHTML = `
    <div class="tl-left cond"><div class="tl-title">LAST 24H</div><div class="tl-hint">drag to rewind</div></div>
    <div class="tl-hist" title="drag to rewind"><div class="bars"></div><div class="playhead"></div></div>
    <div class="now-pill cond">● NOW</div>`;
  attachScrub(el.querySelector(".tl-hist"), (frac) => enterReplay(Date.now() / 1000 - DAY + frac * DAY, DAY));
  renderLiveStrip();
  liveTimer = setInterval(renderLiveStrip, 30000);
}

export async function renderLiveStrip() {
  if (!el || state.mode !== "live") return;
  const now = Date.now() / 1000;
  const buckets = await getBuckets(now - DAY, now, 96);
  drawBars(el.querySelector(".bars"), buckets, true);
}

/* ---------- Replay ---------- */
async function enterReplay(t, span) {
  set({ mode: "replay", playing: false });
  document.getElementById("app").setAttribute("data-mode", "replay");
  syncModeButtons("replay");
  winEnd = Date.now() / 1000;
  winStart = winEnd - span;
  set({ window: span, playheadTime: Math.min(Math.max(t, winStart), winEnd) });
  await loadWindow();
  renderReplayPanel();
  frame();
}

function backToLive() {
  if (raf) cancelAnimationFrame(raf);
  set({ mode: "live", playing: false, playheadTime: null, tracks: [] });
  document.getElementById("app").setAttribute("data-mode", "live");
  syncModeButtons("live");
  clearAircraft();
  renderLivePanel();
  if (onLiveResume) onLiveResume();
}

async function loadWindow() {
  set({ tracks: await getHistory(winStart, winEnd) });
}

function renderReplayPanel() {
  if (liveTimer) clearInterval(liveTimer);
  el.classList.add("replay");
  el.innerHTML = `
    <div class="tl-transport">
      <button class="playpause">▶</button>
      <button class="speed cond">${state.speed}×</button>
    </div>
    <div class="tl-mid">
      <div class="tl-clock num"></div>
      <div class="tl-chips">
        <button class="win-chip cond" data-win="3600">1h</button>
        <button class="win-chip cond" data-win="21600">6h</button>
        <button class="win-chip cond" data-win="86400">24h</button>
      </div>
      <div class="tl-hist"><div class="bars"></div><div class="playhead rp"></div></div>
    </div>
    <button class="back-to-live cond">● BACK TO LIVE →</button>`;
  el.querySelector(".playpause").addEventListener("click", togglePlay);
  el.querySelector(".speed").addEventListener("click", cycleSpeed);
  el.querySelector(".back-to-live").addEventListener("click", backToLive);
  el.querySelectorAll(".win-chip").forEach((c) => {
    c.classList.toggle("active", Number(c.dataset.win) === state.window);
    c.addEventListener("click", () => changeWindow(Number(c.dataset.win)));
  });
  attachScrub(el.querySelector(".tl-hist"), (frac) => {
    set({ playheadTime: winStart + frac * (winEnd - winStart) });
    frame();
  });
  getBuckets(winStart, winEnd, 72).then((b) => drawBars(el.querySelector(".bars"), b, false));
}

async function changeWindow(span) {
  winEnd = Date.now() / 1000; winStart = winEnd - span;
  set({ window: span, playheadTime: Math.min(Math.max(state.playheadTime, winStart), winEnd) });
  await loadWindow();
  renderReplayPanel();
  frame();
}

function togglePlay() {
  set({ playing: !state.playing });
  el.querySelector(".playpause").textContent = state.playing ? "❚❚" : "▶";
  if (state.playing) {
    if (state.playheadTime >= winEnd) set({ playheadTime: winStart });
    lastFrame = performance.now();
    if (!reducedMotion()) raf = requestAnimationFrame(tick);
    else frame();
  } else if (raf) cancelAnimationFrame(raf);
}

function cycleSpeed() {
  const next = { 1: 5, 5: 20, 20: 1 }[state.speed] || 5;
  set({ speed: next });
  el.querySelector(".speed").textContent = `${next}×`;
}

function tick(now) {
  if (!state.playing) return;
  const dt = (now - lastFrame) / 1000; lastFrame = now;
  set({ playheadTime: Math.min(winEnd, state.playheadTime + dt * state.speed) });
  frame();
  if (state.playheadTime >= winEnd) { set({ playing: false });
    el.querySelector(".playpause").textContent = "▶"; return; }
  raf = requestAnimationFrame(tick);
}

function frame() {
  if (state.mode !== "replay") return;
  const t = state.playheadTime;
  const shown = renderReplay(state.tracks, t);
  const clock = el.querySelector(".tl-clock");
  if (clock) clock.textContent = new Date(t * 1000).toLocaleTimeString();
  const ph = el.querySelector(".playhead");
  if (ph && winEnd > winStart) ph.style.right = `${(1 - (t - winStart) / (winEnd - winStart)) * 100}%`;
  const hint = el.querySelector(".tl-hint");
  if (hint) hint.textContent = `${shown} in view`;
}

/* ---------- shared ---------- */
function drawBars(bars, buckets, markLast) {
  if (!bars) return;
  const max = Math.max(1, ...buckets.map((b) => b.count));
  bars.innerHTML = buckets.map((b, i) => {
    const h = (b.count / max) * 100;
    const live = markLast && i === buckets.length - 1 ? " live" : "";
    return `<div class="bar${live}" style="height:${h}%" title="${b.count}"></div>`;
  }).join("");
}

function attachScrub(hist, onFrac) {
  if (!hist) return;
  const toFrac = (e) => {
    const r = hist.getBoundingClientRect();
    return Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
  };
  let dragging = false;
  hist.addEventListener("pointerdown", (e) => { dragging = true; hist.setPointerCapture(e.pointerId); onFrac(toFrac(e)); });
  hist.addEventListener("pointermove", (e) => { if (dragging) onFrac(toFrac(e)); });
  hist.addEventListener("pointerup", () => { dragging = false; });
}

function syncModeButtons(mode) {
  document.querySelectorAll(".mode-seg").forEach((b) =>
    b.classList.toggle("active", b.dataset.mode === mode));
}

export function setModeFromSidebar(mode) {
  if (mode === "replay" && state.mode !== "replay") enterReplay(Date.now() / 1000, state.window || DAY);
  else if (mode === "live" && state.mode !== "live") backToLive();
}
