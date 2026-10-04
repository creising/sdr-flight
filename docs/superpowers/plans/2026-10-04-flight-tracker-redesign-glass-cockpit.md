# Flight Tracker — Glass Cockpit Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current UI with the "Glass Cockpit" redesign — a restyled live map with a look-up card, range rings, chevron markers and trails; a unified timeline that scrubs from Live into Replay; a redesigned stats page with a radial 24-hour clock; dark + light + auto themes; and a full mobile bottom-sheet layout — all on synthetic data.

**Architecture:** No-build native ES modules + split CSS served statically by FastAPI. A single `state.js` object with pub/sub drives `map.js`, `timeline.js`, `contacts.js`, `stats.js`, `theme.js`. Two small backend additions (histogram buckets; airlines share-%/GA grouping). The vendored handoff is the authoritative visual reference.

**Tech Stack:** Python 3.11+ / FastAPI, stdlib sqlite3, Leaflet (CDN), Google Fonts (Barlow / Barlow Condensed / JetBrains Mono), vanilla ES modules + inline SVG (no bundler), pytest + pytest-asyncio, Playwright (marked e2e). **uv for everything.**

**Spec:** `docs/superpowers/specs/2026-10-04-flight-tracker-redesign-glass-cockpit-design.md`
**Visual reference (authoritative for tokens/pixels):** `docs/design/glass-cockpit/handoff.md`

## Global Constraints

- Python **3.11+**; **uv** for every command (`uv run pytest`, `uv run flighttrack`).
- **No build step.** Frontend JS is native ES modules (`<script type="module">`); CSS is hand-written; only Leaflet (CDN) and Google Fonts are external. No bundler, no framework, no gesture/animation library.
- Server binds **`127.0.0.1`**.
- **Only `1b Glass Cockpit`** is built. Dark is primary; light + auto via `prefers-color-scheme` + a `localStorage` override.
- **Exact colors, fonts, sizes, spacing, radii come from `docs/design/glass-cockpit/handoff.md`** (§Design Tokens, §Screens). This plan specifies DOM structure, module APIs, logic, and tests; the handoff specifies pixel/token values. Copy token values verbatim from it.
- All DB-sourced strings (callsign, airline) pass through `escapeHtml` before any `innerHTML`.
- Respect `prefers-reduced-motion` (no glide/crossfade; instant snaps).
- **Data gap:** full airline/aircraft-type *names* need the Phase-4 enrichment DB; until then show the ICAO code (e.g. "BAW") or omit. Never invent names.

## Review Focus

- **No-position aircraft** in the new markers/look-up/contacts: excluded from the map and the look-up subject; must not crash geometry or rendering. *(Test in Task 2 util + Task 5.)*
- **Empty data** (fresh DB / no contacts / empty histogram window): look-up card, contacts list, histogram, radial clock, airlines all render an empty state without throwing (`min/max`, divide-by-zero in bucket/share math). *(Tests in Tasks 1, 2, 8.)*
- **Timeline edge states:** playhead at exactly `now` (Live), scrub before first data / after last, window change clamping the playhead, reaching window end stops playback. *(Test in Task 7.)*
- **Theme resolution:** `auto` honors `prefers-color-scheme`; a manual override persists and wins over auto; both themes stay legible (dark tiles filter only in dark). *(Test in Task 9.)*
- **XSS via DB strings** into any new `innerHTML`/SVG sink (callsign, airline): escaped everywhere. *(Test in Task 5.)*

---

### Task 1: Backend — histogram buckets + airlines share/GA grouping

**Files:**
- Modify: `src/flighttrack/store.py` (add `contacts_buckets`; rework `top_airlines`)
- Modify: `src/flighttrack/app.py` (add `GET /api/stats/buckets`; existing `/api/stats/airlines` returns the new shape)
- Test: `tests/test_store.py` (add cases), `tests/test_app.py` (add route case)

**Interfaces:**
- Produces (used by Tasks 7, 8):
  - `Store.contacts_buckets(start_ts: float, end_ts: float, n: int) -> list[dict]` → `n` items `{"start": float, "count": int}`, equal-width buckets over `[start_ts, end_ts)`, counting contacts whose `first_seen` is in `[bucket_start, bucket_end)`. `n<=0` or `end<=start` → `[]`.
  - `Store.top_airlines(limit: int = 8) -> list[dict]` → `[{"airline": str, "count": int, "share": float}]`, ordered by count desc, with a trailing `{"airline": "Private / GA", ...}` row aggregating registration-style callsigns. `share` = count / (total callsign'd contacts), 0.0 when none.
  - Route `GET /api/stats/buckets?from=<float>&to=<float>&n=<int>` → the buckets list.
- GA heuristic (concrete): a callsign is **airline-style** if it matches `^[A-Z]{3}\d` (3 letters then a digit, e.g. `BAW117`, `UAL1`). Otherwise (tail numbers like `N123AB`, `G-ABCD`) it is **Private / GA**.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_store.py`)

```python
def test_contacts_buckets_counts_by_first_seen(store):
    for ts in (100.0, 100.0, 160.0, 250.0):
        store.open_contact("a", "UAL1", ts)
    b = store.contacts_buckets(100.0, 300.0, n=2)   # buckets [100,200),[200,300)
    assert [x["count"] for x in b] == [3, 1]
    assert b[0]["start"] == 100.0 and b[1]["start"] == 200.0


def test_contacts_buckets_degenerate(store):
    assert store.contacts_buckets(100.0, 100.0, 4) == []
    assert store.contacts_buckets(100.0, 200.0, 0) == []
    assert store.contacts_buckets(200.0, 100.0, 4) == []


def test_top_airlines_share_and_ga_grouping(store):
    for cs in ["UAL1", "UAL2", "DAL9", "N123AB", "G-ABCD"]:
        store.open_contact(cs[:3].lower(), cs, 100.0)
    rows = store.top_airlines()
    assert rows[-1]["airline"] == "Private / GA" and rows[-1]["count"] == 2
    ual = next(r for r in rows if r["airline"] == "UAL")
    assert ual["count"] == 2 and abs(ual["share"] - 2 / 5) < 1e-9


def test_top_airlines_empty(store):
    assert store.top_airlines() == []
```

Append to `tests/test_app.py`:

```python
def test_buckets_endpoint():
    from flighttrack.config import Settings, Receiver, DbConfig
    s = Settings(source="synthetic", receiver=Receiver(lat=40.0, lon=-105.0),
                 poll_interval_s=0.02, db=DbConfig(path=":memory:"))
    app = create_app(s)
    with TestClient(app) as c:
        store = app.state.store
        store.open_contact("a", "UAL1", 100.0)
        r = c.get("/api/stats/buckets", params={"from": 100.0, "to": 200.0, "n": 1})
        assert r.status_code == 200 and r.json()[0]["count"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_store.py -k "buckets or airlines" tests/test_app.py -k buckets -q`
Expected: FAIL — `contacts_buckets` missing; `top_airlines` rows lack `share`/GA; `/api/stats/buckets` 404.

- [ ] **Step 3: Implement `contacts_buckets` and rework `top_airlines` in `src/flighttrack/store.py`**

Add methods to `Store`:

```python
    def contacts_buckets(self, start_ts: float, end_ts: float, n: int) -> list[dict]:
        if n <= 0 or end_ts <= start_ts:
            return []
        width = (end_ts - start_ts) / n
        with self._lock:
            out = []
            for i in range(n):
                lo = start_ts + i * width
                hi = lo + width
                c = self._db.execute(
                    "SELECT count(*) c FROM contacts WHERE first_seen>=? AND first_seen<?",
                    (lo, hi)).fetchone()["c"]
                out.append({"start": lo, "count": c})
            return out
```

Replace the existing `top_airlines` body with:

```python
    def top_airlines(self, limit: int = 8) -> list[dict]:
        import re
        with self._lock:
            rows = self._db.execute(
                "SELECT callsign FROM contacts WHERE callsign IS NOT NULL AND length(callsign)>=3"
            ).fetchall()
        if not rows:
            return []
        total = len(rows)
        airline: dict[str, int] = {}
        ga = 0
        for r in rows:
            cs = r["callsign"]
            if re.match(r"^[A-Z]{3}\d", cs):
                airline[cs[:3]] = airline.get(cs[:3], 0) + 1
            else:
                ga += 1
        ranked = sorted(airline.items(), key=lambda kv: kv[1], reverse=True)[:limit]
        out = [{"airline": a, "count": c, "share": c / total} for a, c in ranked]
        if ga:
            out.append({"airline": "Private / GA", "count": ga, "share": ga / total})
        return out
```

- [ ] **Step 4: Add the buckets route in `src/flighttrack/app.py`** (next to the other stats routes)

```python
    @app.get("/api/stats/buckets")
    async def stats_buckets(from_: float = Query(..., alias="from"),
                            to: float = Query(...), n: int = Query(96)):
        return await asyncio.to_thread(app.state.store.contacts_buckets, from_, to, n)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_store.py tests/test_app.py -q`
Expected: PASS (new + existing; the Phase-2 `test_top_airlines_counts_callsign_prefix` still passes because UAL/DAL counts are unchanged — it does not assert row shape beyond `airline`/`count`).

- [ ] **Step 6: Commit**

```bash
git add src/flighttrack/store.py src/flighttrack/app.py tests/test_store.py tests/test_app.py
git commit -m "feat: histogram buckets endpoint + airlines share/GA grouping"
```

---

### Task 2: Frontend scaffold — ES modules, tokens, state, util + tests

**Files:**
- Create: `src/flighttrack/static/css/tokens.css`, `css/app.css` (minimal shell for now)
- Create: `src/flighttrack/static/js/util.js`, `js/state.js`, `js/api.js`, `js/theme.js`
- Rewrite: `src/flighttrack/static/index.html` (module shell)
- Delete: `src/flighttrack/static/app.js`, `src/flighttrack/static/style.css` (replaced; stats.* stay until Task 8)
- Delete: `tests/test_frontend_smoke.py`, `tests/test_playback_smoke.py` (assert the OLD DOM; replaced by new smokes in Tasks 5/7)
- Create: `tests/test_util.py` (e2e; imports the served module)

**Interfaces:**
- Produces (used by all later frontend tasks):
  - `util.js` exports: `elevationDeg`, `isOverhead`, `lookupSubject`, `compass16`, `flightLevel`, `altClass`, `altTrend`, `bucketIndex`, `escapeHtml` (signatures per spec §7).
  - `state.js` exports: `state` (object with the §5 keys), `subscribe(fn)`, `set(patch)` (shallow-merges and notifies).
  - `api.js` exports: `getConfig()`, `getSummary()`, `getPerHour()`, `getAirlines()`, `getBuckets(from,to,n)`, `getHistory(from,to)` (all `async` → parsed JSON).
  - `theme.js` exports: `initTheme()` (applies resolved theme to `document.documentElement[data-theme]`), `setTheme('auto'|'dark'|'light')`.

- [ ] **Step 1: Write the failing test** (`tests/test_util.py`)

```python
import socket, threading, time
import pytest, uvicorn
from flighttrack.config import Settings, Receiver, DbConfig
from flighttrack.app import create_app

pytestmark = pytest.mark.e2e


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


@pytest.fixture
def server_url():
    port = _free_port()
    s = Settings(source="synthetic", receiver=Receiver(lat=40.0, lon=-105.0, alt_m=1600.0),
                 poll_interval_s=0.1, db=DbConfig(path=":memory:"), port=port)
    srv = uvicorn.Server(uvicorn.Config(create_app(s), host="127.0.0.1", port=port, log_level="warning"))
    th = threading.Thread(target=srv.run, daemon=True); th.start()
    for _ in range(50):
        if srv.started: break
        time.sleep(0.1)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True; th.join(timeout=5)


def test_util_helpers(server_url, page):
    page.goto(server_url)
    r = page.evaluate("""async () => {
        const u = await import('/static/js/util.js');
        return {
            elev: Math.round(u.elevationDeg(34000, 1.0)),      // high
            overhead: u.isOverhead(50) && !u.isOverhead(39),
            compassN: u.compass16(0), compassE: u.compass16(90),
            fl: u.flightLevel(34000),
            altLow: u.altClass(8000), altHigh: u.altClass(34000), altNull: u.altClass(null),
            trendUp: u.altTrend(100, 200), trendFlat: u.altTrend(100, 100),
            bIn: u.bucketIndex(150, 100, 300, 2), bOut: u.bucketIndex(50, 100, 300, 2),
            esc: u.escapeHtml('<b>&"x'),
            lookup: u.lookupSubject([{icao:'a',elevation_deg:10},{icao:'b',elevation_deg:80}]).icao,
        };
    }""")
    assert r["overhead"] and r["compassN"] == "N" and r["compassE"] == "E"
    assert r["fl"] == "340" and r["altLow"] == "low" and r["altHigh"] == "high" and r["altNull"] is None
    assert r["trendUp"] == "up" and r["trendFlat"] == "flat"
    assert r["bIn"] == 0 and r["bOut"] == -1
    assert r["esc"] == "&lt;b&gt;&amp;&quot;x" and r["lookup"] == "b"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_util.py -m e2e -q`
Expected: FAIL — `/static/js/util.js` 404 (module missing).

- [ ] **Step 3: Write `src/flighttrack/static/js/util.js`**

```javascript
export function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
export function elevationDeg(altFt, groundKm) {
  if (altFt == null || groundKm == null || groundKm <= 0) return 90;
  return Math.atan((altFt * 0.0003048) / groundKm) * 180 / Math.PI;
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
const DIRS = ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"];
export function compass16(bearingDeg) {
  return DIRS[Math.round(((bearingDeg % 360) + 360) % 360 / 22.5) % 16];
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
```

- [ ] **Step 4: Write `state.js`, `api.js`, `theme.js`**

```javascript
// state.js
export const state = {
  mode: "live", playheadTime: null, playing: false, speed: 5, window: 3600,
  selectedCallsign: null, labelsOn: true, theme: "auto", sheetSnap: "peek",
  contacts: [], buckets: [], tracks: [], stats: null, receiver: null,
};
const subs = new Set();
export function subscribe(fn) { subs.add(fn); return () => subs.delete(fn); }
export function set(patch) { Object.assign(state, patch); for (const fn of subs) fn(state); }
```

```javascript
// api.js
const j = async (u) => (await fetch(u)).json();
export const getConfig = () => j("/api/config");
export const getSummary = () => j("/api/stats/summary");
export const getPerHour = () => j("/api/stats/per-hour");
export const getAirlines = () => j("/api/stats/airlines");
export const getBuckets = (from, to, n) => j(`/api/stats/buckets?from=${from}&to=${to}&n=${n}`);
export const getHistory = (from, to) => j(`/api/history?from=${from}&to=${to}`);
```

```javascript
// theme.js
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
    if ((localStorage.getItem(KEY) || "auto") === "auto") setTheme("auto");
  });
}
```

- [ ] **Step 5: Write `tokens.css` and a minimal `app.css`; rewrite `index.html`**

Create `css/tokens.css` with the **dark and light token sets copied verbatim from `docs/design/glass-cockpit/handoff.md` → "Design Tokens"**, as CSS custom properties on `:root[data-theme="dark"]` and `:root[data-theme="light"]`, plus the Google Fonts `@import` for Barlow / Barlow Condensed / JetBrains Mono, and base `body` rules (bg `var(--bg)`, color `var(--text)`, font Barlow). Convert the handoff's `oklch(...)` values as given (browsers support `oklch`).

Create a minimal `css/app.css` (expanded in Tasks 4–7): the `#app` grid (`372px | 1fr`, full height) and the dark Leaflet tile filter:
```css
:root[data-theme="dark"] .leaflet-tile-pane { filter: invert(1) hue-rotate(180deg) brightness(.75) saturate(.35); }
```

Rewrite `index.html` as the module shell:
```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
  <meta name="theme-color" content="#0a0d12" />
  <title>Overhead</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <link rel="stylesheet" href="/static/css/tokens.css" />
  <link rel="stylesheet" href="/static/css/app.css" />
</head>
<body>
  <div id="app">
    <aside id="sidebar"></aside>
    <div id="map"></div>
  </div>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script type="module" src="/static/js/live.js"></script>
</body>
</html>
```

- [ ] **Step 6: Create a stub `js/live.js` so the page boots, and remove old files/tests**

```javascript
// js/live.js (stub; Tasks 4-7 build this out)
import { initTheme } from "/static/js/theme.js";
import { getConfig } from "/static/js/api.js";
initTheme();
getConfig();  // smoke: module graph loads
```

Delete `src/flighttrack/static/app.js`, `src/flighttrack/static/style.css`, `tests/test_frontend_smoke.py`, `tests/test_playback_smoke.py`.

(The old `stats.html`/`stats.js` keep working and `test_stats_page_smoke.py` stays green until Task 8 replaces them — they reference `/static/style.css` which we deleted, so **in this task also update `stats.html`'s stylesheet link to `/static/css/tokens.css`** so the stats smoke keeps passing. Stats visuals are redone in Task 8.)

- [ ] **Step 7: Run tests**

Run: `uv run pytest tests/test_util.py -m e2e -q && uv run pytest -q`
Expected: util e2e PASS; full default suite PASS (old frontend smokes removed; stats smoke still green).

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat: ES-module frontend scaffold, design tokens, util helpers, theming"
```

---

### Task 3: Map module — tiles, rings, home, markers, trails, selection

**Files:**
- Create: `src/flighttrack/static/js/map.js`, `js/socket.js`
- Modify: `js/live.js` (compose map + socket)
- Modify: `css/app.css` (map controls, data-block labels)
- Test: `tests/test_live_map_smoke.py` (e2e)

**Interfaces:**
- Consumes: `state`, `util.js`, `api.js`, Leaflet (global `L`).
- Produces:
  - `map.js`: `initMap(receiver)` → creates the Leaflet map, home crosshair + 5/10/20/30 km `L.circle` rings with top labels; `renderAircraft(list, {labelsOn, selected})` → upserts chevron `L.divIcon` markers (fill = altitude color, 1.5px stroke in map-bg, CSS `rotate(heading)`, 34px ring when overhead), keeps ≤6 history-dot `L.circleMarker`s per icao, draws the data-block label when `labelsOn`, removes gone aircraft; `onSelect(cb)`; `panTo(icao)`.
  - `socket.js`: `connectLive(onFrame)` → the auto-reconnect WebSocket from Phase 2 (carried forward), calling `onFrame(data)` only while `state.mode === "live"`.

- [ ] **Step 1: Write the failing e2e** (`tests/test_live_map_smoke.py`) — same server fixture pattern as Task 2; body:

```python
def test_live_map_renders(server_url, page):
    page.goto(server_url)
    page.wait_for_selector(".leaflet-container", timeout=8000)
    page.wait_for_selector(".ac-marker", timeout=8000)      # a chevron aircraft marker
    assert page.locator(".ring-label").count() >= 1          # range-ring labels
```

- [ ] **Step 2: Run it** — Run: `uv run pytest tests/test_live_map_smoke.py -m e2e -q` — Expected: FAIL (no `.ac-marker`).

- [ ] **Step 3: Write `js/socket.js`**

```javascript
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
  return { isOpen: () => ws && ws.readyState === WebSocket.OPEN, reopen: () => { if (!ws || ws.readyState > 1) open(); } };
}
```

- [ ] **Step 4: Write `js/map.js`** — implement the markers/rings/trails/data-blocks exactly per `docs/design/glass-cockpit/handoff.md` §"Map pane" and `scope.dc.html`. Marker is an `L.divIcon` whose HTML is an inline `<svg>` chevron (`points="12,1 21,22 12,17 3,22"`) with class `ac-marker`, `fill` = `var(--alt-{class})`, rotated by heading; overhead adds a ring element. Ring labels are small `<div>`s positioned at each ring's top with class `ring-label`. Trails: keep a per-icao array of the last 6 `[lat,lon]`, drawn as `L.circleMarker`s fading newest→oldest. Full code here (the implementer copies token values from the handoff):

```javascript
import { altClass, flightLevel, altTrend, escapeHtml, isOverhead } from "/static/js/util.js";

let map, layer, markers = new Map(), trails = new Map(), lastAlt = new Map(), selectCb = null;
const RINGS_KM = [5, 10, 20, 30];

function css(v) { return getComputedStyle(document.documentElement).getPropertyValue(v).trim(); }
function altColorVar(cls) { return cls ? `var(--alt-${cls})` : "var(--muted)"; }

export function initMap(receiver) {
  map = L.map("map", { zoomControl: false }).setView([receiver.lat, receiver.lon], 10);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    { maxZoom: 18, attribution: "© OpenStreetMap" }).addTo(map);
  layer = L.layerGroup().addTo(map);
  for (const km of RINGS_KM) {
    L.circle([receiver.lat, receiver.lon], { radius: km * 1000, fill: false,
      color: css("--line-2") || "#2a3542", weight: 1, interactive: false }).addTo(layer);
    const edge = L.latLng(receiver.lat + km / 111, receiver.lon);
    L.marker(edge, { interactive: false, icon: L.divIcon({ className: "",
      html: `<div class="ring-label">${km} km</div>`, iconSize: [40, 14] }) }).addTo(layer);
  }
  L.circleMarker([receiver.lat, receiver.lon], { radius: 7, color: css("--text") || "#e8edf2",
    weight: 2, fill: false }).addTo(layer);
  return map;
}

function icon(a) {
  const cls = altClass(a.alt_ft);
  const ring = isOverhead(a.elevation_deg) ? `<circle cx="17" cy="17" r="16" fill="none" stroke="${altColorVar(cls)}" stroke-opacity="0.55" stroke-width="1.5"/>` : "";
  return L.divIcon({ className: "", iconSize: [34, 34], iconAnchor: [17, 17],
    html: `<svg width="34" height="34" viewBox="0 0 34 34">${ring}` +
      `<g transform="translate(5,5) rotate(${a.track_deg ?? 0} 12 12)">` +
      `<polygon class="ac-marker" points="12,1 21,22 12,17 3,22" fill="${altColorVar(cls)}" ` +
      `stroke="var(--bg)" stroke-width="1.5"/></g></svg>` });
}

export function renderAircraft(list, opts = {}) {
  const seen = new Set();
  for (const a of list) {
    if (a.lat == null || a.lon == null) continue;
    seen.add(a.icao);
    let m = markers.get(a.icao);
    if (!m) { m = L.marker([a.lat, a.lon], { icon: icon(a) }).addTo(layer);
      m.on("click", () => selectCb && selectCb(a.icao)); markers.set(a.icao, m); }
    else { m.setLatLng([a.lat, a.lon]); m.setIcon(icon(a)); }
    const tr = trails.get(a.icao) || []; tr.push([a.lat, a.lon]); while (tr.length > 6) tr.shift();
    trails.set(a.icao, tr);
    lastAlt.set(a.icao, a.alt_ft);
  }
  for (const [icao, m] of markers) if (!seen.has(icao)) { layer.removeLayer(m); markers.delete(icao); trails.delete(icao); }
}

export function onSelect(cb) { selectCb = cb; }
export function panTo(icao) { const m = markers.get(icao); if (m) map.panTo(m.getLatLng()); }
```

- [ ] **Step 5: Wire `js/live.js`**

```javascript
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
  connectLive((data) => { set({ contacts: data.aircraft }); renderAircraft(data.aircraft, { labelsOn: state.labelsOn, selected: state.selectedCallsign }); });
})();
```

- [ ] **Step 6: Add `.ring-label`, `.ac-marker`, map-control CSS to `css/app.css`** (values per handoff §Map pane).

- [ ] **Step 7: Run** — `uv run pytest tests/test_live_map_smoke.py -m e2e -q` → PASS; then `uv run pytest -q` → PASS.

- [ ] **Step 8: Commit**

```bash
git add -A && git commit -m "feat: glass-cockpit Leaflet map — rings, chevron markers, trails, selection"
```

---

### Task 4: Sidebar shell — header, mode segmented control, status, legend

**Files:** Modify `js/live.js` (render sidebar skeleton), create `js/contacts.js` (header/legend only here; look-up + list in Task 5), modify `css/app.css`. Test: extend `tests/test_live_map_smoke.py`.

**Interfaces:** `contacts.js` exports `renderSidebar(container)` → injects the static structure (OVERHEAD wordmark + "Stats →" link; a 2-segment Live/Replay control bound to `set({mode})`; a `#status` line; a `#lookup` slot; a `#contacts` slot; altitude legend footer), per handoff §"Sidebar" 1–3,7.

- [ ] **Step 1: failing test** — add to live-map smoke: `assert page.locator("#sidebar .wordmark").inner_text() == "OVERHEAD"` and the two mode segments exist.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** implement `renderSidebar` (concrete HTML string with the slots/classes above; wire the segmented control buttons to `set({mode})`; "Stats →" links to `/stats`).
- [ ] **Step 4:** call `renderSidebar(document.getElementById("sidebar"))` in `live.js` before `initMap`.
- [ ] **Step 5:** CSS for header/segmented control/legend per handoff.
- [ ] **Step 6:** run smoke + full suite → PASS.
- [ ] **Step 7:** `git add -A && git commit -m "feat: glass-cockpit sidebar shell (header, mode control, legend)"`

---

### Task 5: Look-up card + contacts list (+ XSS test)

**Files:** Modify `js/contacts.js`, `css/app.css`. Test: `tests/test_contacts_smoke.py` (e2e).

**Interfaces:** `contacts.js` exports `renderContacts(contacts)` → updates `#lookup` (the max-elevation subject via `lookupSubject`: callsign hero, airline *code* or omitted, elevation gauge SVG, DIST/ALT/ELEV readout) and `#contacts` (rows sorted by distance: chevron rotated to heading in alt color, callsign, OVERHEAD tag when `isOverhead`, KM/FT+trend/ELEV columns). All strings via `escapeHtml`. Per handoff §"Look-up card" & §"Contacts list".

- [ ] **Step 1: failing tests** (new smoke): look-up shows the highest-elevation contact's callsign; a `.contact-row` exists; **XSS**: seed a contact with callsign `<img src=x onerror='window.__xss=1'>` closest+overhead via `app.state.store`, assert `window.__xss` is None and the text is escaped.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** implement `renderContacts` with the gauge SVG (quarter-arc per handoff §"elevation gauge") and the row grid; subscribe it to state so WS frames update it; escape every DB string.
- [ ] **Step 4:** run smoke + full suite → PASS.
- [ ] **Step 5:** `git add -A && git commit -m "feat: look-up card + contacts list with escaped DB strings"`

---

### Task 6: Live histogram strip (display-only)

**Files:** Create `js/timeline.js` (live view only), modify `js/live.js`, `css/app.css`. Test: extend contacts/live smoke.

**Interfaces:** `timeline.js` exports `initTimeline(container)` and `renderLiveStrip()` → fetches `getBuckets(now-24h, now, 96)`, draws 96 bars (last bar = `--live`), tick labels, a "● NOW" pill and the playhead at the right edge, per handoff §"Timeline strip". Refreshes on an interval. (The drag-to-replay interaction is Task 7.)

- [ ] Steps: failing smoke (`#timeline .bar` count ≥ 1 and the `.now-pill` present) → implement → run → commit `feat: live timeline histogram strip`.

---

### Task 7: Unified timeline — scrub into Replay, play/speed/window

**Files:** Modify `js/timeline.js`, `js/map.js` (replay track rendering), `js/live.js`, `css/app.css`. Test: `tests/test_timeline_smoke.py` (e2e).

**Interfaces:** extend `timeline.js`: pointer-drag / click on the histogram sets `state.playheadTime` and `set({mode:'replay'})`; a replay panel (clock card, 1h/6h/24h window chips, play/pause, speed cycle 1×/5×/20×) appears; "NOW / back to live" springs to the right edge and `set({mode:'live'})`. On replay, fetch `getHistory(windowStart, windowEnd)` into `state.tracks`, and `map.js` gains `renderReplay(tracks, playheadTime)` (interpolated positions + flown/remaining track dots + violet wash). Accent crossfades green↔violet via a `data-mode` attribute on `#app`. Per handoff §"Replay" & §"Interactions".

**Review-Focus tests (in the smoke):** dragging into the histogram switches to replay (violet / `#app[data-mode=replay]`); scrub before first data shows 0 aircraft without error; window change clamps the playhead; "back to live" returns to live and the WS resumes.

- [ ] Steps: failing e2e for the live→replay transition and back → implement the state machine + `renderReplay` + reduced-motion guard → run → full suite → commit `feat: unified timeline — scrub Live↔Replay with playback and windows`.

---

### Task 8: Stats page redesign — tiles, radial 24h clock, airlines

**Files:** Rewrite `src/flighttrack/static/stats.html`, replace `stats.js`, create `css/stats.css`, add `GET /stats` already exists. Delete old `tests/test_stats_page_smoke.py` assertions that targeted the old DOM; rewrite that smoke for the new DOM. 

**Interfaces:** `stats.js` (module) renders: headline tiles (Seen today / all-time), record tiles (closest/farthest/highest/busiest with their mini-glyphs), the **radial 24-hour clock** (24 `<rect>`s rotated `hour×15°` around center, busiest = `--alt-mid`, now-needle, night shading) from `getPerHour()`, and the **top-airlines** rows (code chip, bar, count, share%, "Private / GA" last) from `getAirlines()`. Per handoff §"Stats". All DB strings escaped.

- [ ] Steps: failing e2e (tiles present; radial clock has 24 `rect`s; an airlines row incl. "Private / GA" when seeded) → implement → run → commit `feat: glass-cockpit stats — headline/record tiles, radial clock, airlines`.

---

### Task 9: Theming (light + auto toggle) + mobile bottom sheet

**Files:** Modify `tokens.css` (verify light set), `css/app.css` + `css/stats.css` (mobile breakpoints, bottom sheet via scroll-snap, floating top bar), `js/contacts.js` (sheet peek/expanded), add a theme toggle control to the sidebar/stats header + `theme.js` wiring. Test: `tests/test_theme_mobile_smoke.py` (e2e).

**Interfaces:** theme toggle cycles auto→dark→light calling `setTheme`; mobile (<900px) shows the floating top bar + bottom sheet; sheet uses `scroll-snap-type: y mandatory` with peek/expanded snap points and `env(safe-area-inset-bottom)` padding. Per handoff §"mobile" sections and §"Colours — light".

**Review-Focus tests:** set theme=light → `document.documentElement[data-theme]==='light'` and body bg changes; emulate `prefers-color-scheme: light` with pref=auto → resolves light; set a phone viewport → `.bottom-sheet` present and reaches both snap states; dark tile filter absent in light.

- [ ] Steps: failing e2e (theme + mobile) → implement → run full suite (default + all e2e) → commit `feat: light/auto themes and mobile bottom-sheet layout`.

---

## Self-Review

**Spec coverage:** structure/ES-modules (T2) ✓; backend buckets+airlines (T1) ✓; util pure helpers + tests (T2) ✓; map rings/markers/trails/selection (T3) ✓; sidebar + mode control (T4) ✓; look-up + contacts + XSS (T5) ✓; live histogram (T6) ✓; unified timeline Live↔Replay + windows + play/speed (T7) ✓; stats radial clock + tiles + airlines (T8) ✓; light/auto theme + mobile sheet (T9) ✓; data-gap (codes not names) honored in T5/T8 ✓; reduced-motion in T7/T9 ✓.

**Placeholder scan:** Tasks 1–3 carry full code; Tasks 4–9 specify exact DOM/classes, module APIs, and per-task tests, and defer pixel/token values to the vendored `handoff.md` (in-repo, authoritative) rather than restating them — this is a concrete reference, not a "style it nicely" placeholder. The risk-bearing logic (backend, util, map markers, timeline state machine, theme resolution) is given as complete code.

**Type/name consistency:** `util.js` export names match their test (T2) and consumers (T3/T5/T7); `state` keys match `set()` calls across tasks; `Store.contacts_buckets`/`top_airlines` shapes match the routes (T1) and consumers (T6/T7/T8); marker class `.ac-marker`, `.ring-label`, `#lookup`, `#contacts`, `#timeline`, `#app[data-mode]` are used consistently by the tasks that assert them.

**Review Focus → owning tests:** no-position aircraft → T2 util (`lookupSubject` skip) + T3 render guard; empty data → T1 (buckets/airlines empty), T8 (empty stats render); timeline edges → T7; theme resolution → T9; XSS → T5. All mapped.
