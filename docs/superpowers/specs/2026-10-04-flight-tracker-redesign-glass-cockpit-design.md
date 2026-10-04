# Flight Tracker — Glass Cockpit Redesign — Design

**Date:** 2026-10-04
**Status:** Approved design (pre-implementation)
**Author:** Chris Reising (with Claude); visual design by Claude Design

## 1. Purpose & Intent

Replace the current functional UI with the **"Glass Cockpit"** visual + interaction
redesign produced by Claude Design. The goal is a personal-aviation-instrument feel:
near-black glass, condensed uppercase labels, large tabular numerals, and color
reserved for meaning. The app's behavior (live ADS-B map, logging, stats, replay) is
unchanged; this is a UI/UX overhaul plus a small amount of new backend data and one
new interaction model (the unified timeline).

Still runs entirely on **synthetic data** — no SDR required — so it is fully
testable on the dev Mac and slots in **before** Phase 3 (deployment).

## 2. Authoritative visual reference

The visual spec is the vendored handoff at **`docs/design/glass-cockpit/handoff.md`**
(design tokens, per-screen specs, interactions, Leaflet notes). The rendered mockups
(`overhead-redesign.dc.html`, `scope.dc.html`, `support.js`) are reference only —
**do not port that `.dc.html` runtime**; recreate everything in the app's stack. Where
this spec and the handoff differ, this spec's scope decisions win; for pixel/token
detail, the handoff is authoritative.

## 3. Scope decisions (locked)

- **Direction:** only **1b Glass Cockpit**. 1a Phosphor / 1c Sectional are not built.
- **Unified timeline (full):** Live = playhead pinned to "now"; dragging/scrubbing into
  the histogram enters Replay; "NOW / Back to live" returns to Live. The segmented
  Live/Replay control is a shortcut for the same state.
- **Themes:** dark (primary) + light (secondary) + auto, via `prefers-color-scheme`
  plus a manual override (persisted in `localStorage`).
- **Mobile (full):** floating top bar + bottom sheet with peek/expanded snap points,
  via CSS `scroll-snap` (no gesture library).
- **Accessibility:** respect `prefers-reduced-motion` (no glide/crossfade, instant
  snaps); maintain the handoff's contrast choices.

## 4. Constraints (unchanged from the project)

- **No build step.** Vanilla HTML/CSS/JS; libraries via CDN only (Leaflet). Frontend
  JS uses **native ES modules** (`<script type="module">`) — no bundler.
- Fonts from **Google Fonts** (Barlow, Barlow Condensed, JetBrains Mono).
- Server binds `127.0.0.1`; served over the tailnet via `tailscale serve`.
- Python backend (FastAPI); **uv** for all tooling.
- SQLite store unchanged except the additions in §6.

## 5. Frontend architecture

No-build ES modules + split CSS, served statically by FastAPI:

```
static/
  index.html          # live map shell (module script -> live.js)
  stats.html          # stats shell (module script -> stats.js)
  css/
    tokens.css        # design tokens: dark + light + auto, font imports, base
    app.css           # live map, sidebar, look-up card, timeline, mobile sheet
    stats.css         # stats page (headline tiles, record tiles, radial clock, airlines)
  js/
    util.js           # PURE helpers (see §7) + escapeHtml  [unit-tested]
    state.js          # the app-state object + simple pub/sub
    api.js            # fetch helpers: /api/config, /api/stats/*, /api/history, /api/stats/buckets
    socket.js         # live WebSocket (auto-reconnect), feeds state
    map.js            # Leaflet: tiles (+dark CSS filter), range rings, home crosshair,
                      #   aircraft markers, history-dot trails, data-block labels, selection
    timeline.js       # unified histogram strip: live playhead <-> drag-to-replay,
                      #   play/pause, speed cycle, window chips, scrub
    contacts.js       # look-up card (+elevation gauge), contacts list, mobile bottom sheet
    theme.js          # auto/dark/light resolution + manual toggle (localStorage)
    live.js           # composes the live map screen from the modules above
    stats.js          # tiles + radial 24h clock + top-airlines rows
```

`app.py` serves the new static tree (the `/static` mount already covers
subdirectories; add no per-file routes). `index.html` and `stats.html` remain the
`/` and `/stats` documents.

State lives in `state.js` as a single object with a tiny subscribe/notify API; modules
subscribe and re-render on change. Keys match the handoff `State` list: `mode`,
`playheadTime`, `playing`, `speed`, `window`, `selectedCallsign`, `labelsOn`, `theme`,
`sheetSnap`, plus data: `contacts` (live), `buckets`, `tracks` (replay), `stats`.

## 6. Backend changes

1. **Histogram buckets** — `Store.contacts_buckets(start_ts: float, end_ts: float, n: int) -> list[dict]`
   returning `n` equal time buckets over `[start, end)`, each `{"start": ts, "count": int}`,
   counting contacts whose `first_seen` falls in the bucket. Used for the live strip
   (n=96 over the last 24h, ~15-min buckets) and the replay histogram (n=72 over the
   selected window). New route `GET /api/stats/buckets?from=<ts>&to=<ts>&n=<int>`.
2. **Airlines upgrade** — `Store.top_airlines(limit)` returns, per row,
   `{"airline": code, "count": int, "share": float}` where `share` = count / total
   contacts-with-callsign; callsigns that are not airline-style (e.g. tail numbers like
   `N123AB` — heuristic: three leading letters that look like an ICAO airline vs a
   registration) are grouped into a single **`"Private / GA"`** row sorted **last**.
   (Absorbs the deferred Phase-2 minor #5.)
3. No other backend changes. Radial clock uses existing `contacts_per_hour`; replay
   tracks use existing `/api/history`; elevation/look-up use existing geometry.

The stale/retention/logging behavior and the `contacts`/`positions` schema are unchanged.

## 7. Pure helpers (`util.js`) — the unit-tested core

- `elevationDeg(altFt, groundKm)` → degrees (`atan(altFt·0.0003048 / groundKm)`).
- `isOverhead(elevDeg)` → `elevDeg >= 40`.
- `lookupSubject(contacts)` → the contact with max elevation (ties: nearest).
- `compass16(bearingDeg)` → one of `N, NNE, …, NNW`.
- `flightLevel(altFt)` → `round(alt/100)` zero-padded to 3 (string).
- `altClass(altFt)` → `"low" | "mid" | "high"` (<10k / <25k / ≥25k; null → neutral).
- `altTrend(prevAltFt, altFt)` → `"up" | "down" | "flat"`.
- `bucketIndex(ts, start, end, n)` → integer bucket or `-1` if out of range.
- `escapeHtml(s)` (shared; all DB-sourced strings pass through it — carries the Phase-2
  XSS fix forward into every new `innerHTML` sink).

These are the risk-bearing logic; they get direct tests (§9).

## 8. Data-availability adaptations (honest gaps)

The mocks show full **airline names** ("British Airways") and **aircraft types** — both
require the **Phase-4 offline enrichment DB**, which does not exist yet. Until then:
- The look-up card's and contacts list's secondary "airline name" line shows the
  **ICAO airline code** (e.g. "BAW") when derivable from the callsign, else is omitted.
- Aircraft-type references in the mocks are omitted.
- "Top airlines" shows **codes** (and the "Private / GA" bucket), not full names.

Everything else (positions, altitude, distance, elevation, speed, heading, callsign,
counts, times, records) uses real synthetic data today and real ADS-B after Phase 3.

## 9. Testing strategy

- **Unit (pytest):** `Store.contacts_buckets` (bucket math, empty window, boundary/edge,
  `from>to`) and the `top_airlines` share-% + "Private / GA" grouping.
- **`util.js` helpers (Playwright, marked e2e):** navigate to the running app and
  `await import('/static/js/util.js')`, asserting each pure function across normal and
  edge inputs (null altitude, zero ground distance, bearing wraparound, out-of-range
  bucket). Real coverage of derived-value math with no JS build.
- **e2e smokes (Playwright):**
  - Live map renders: markers, range rings, home crosshair; look-up card shows the
    **highest-elevation** contact.
  - **Unified timeline:** scrubbing/dragging into the histogram switches `mode` to
    `replay` (violet accent applied); "NOW / back to live" returns to `live`.
  - **Theme:** toggling to light applies light tokens (observable via a token/body
    style); auto honors `prefers-color-scheme`.
  - **Mobile** (phone viewport): floating top bar present; bottom sheet reaches
    peek and expanded snap states.
  - **Stats:** headline tiles, radial clock (24 `<rect>` bars), airlines rows incl.
    the "Private / GA" row.
- Existing Phase-1/2 backend tests remain green; the WS/stats/history APIs they cover
  are unchanged except the two additions above.

## 10. Non-goals (this phase)

- No SDR/deployment work (Phase 3), no alerts/Web Push/PWA-install (Phase 4).
- No offline enrichment DB (airline/type names) — see §8.
- Directions 1a/1c are not built.
- No gesture/animation library; no bundler/build step introduced.

## 11. Risks

- **Scope size:** this is the largest frontend change in the project. Mitigated by the
  module split (§5), the handoff carrying the visual detail, and a staged plan.
- **Leaflet + custom markers/trails performance** at many aircraft: acceptable at
  hobby scale; markers use `L.divIcon`, trails use capped (≤6) `L.circleMarker`s.
- **Unified-timeline state machine** is the trickiest piece; it gets dedicated e2e
  coverage for the live↔replay transition.
