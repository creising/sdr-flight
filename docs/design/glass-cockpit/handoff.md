# Handoff: Overhead — "Glass cockpit" redesign

## Overview
Visual redesign of **Overhead**, a single-user personal ADS-B flight tracker (SDR on a home server → 1090 MHz → live map + logging + replay). Two screens: **Live Map** (primary, with Live/Replay modes) and **Stats** (`/stats`). Target: installable PWA, phone + laptop, dark theme primary, light theme secondary. Chosen direction: **1b "Glass cockpit"** — near-black glass, condensed labels, big tabular numerals, colour reserved for meaning.

## About the Design Files
The files in this bundle are **design references created in HTML** — prototypes showing intended look and behaviour, not production code to copy. Recreate them in the existing app's environment: **vanilla HTML/CSS/JS + Leaflet, no build step, CDN-only libraries**. Do not port the `.dc.html` component runtime (`support.js`); it exists only to render the mockups.

Open `Overhead Redesign.dc.html` in a browser to see the canvas. `Scope.dc.html` is the stylised stand-in for the Leaflet map (range rings, markers, trails). The map background in the mocks is a placeholder — real tiles come from OSM via Leaflet.

## Fidelity
**High-fidelity** for colours, typography, spacing, component structure and interactions. Data values (callsigns, counts, dates) are fictional. Replay demo speed is accelerated and not representative.

---

## Design Tokens

### Colours — dark (primary)
| Token | Value | Use |
|---|---|---|
| `--bg` | `#0a0d12` | page / map base |
| `--sidebar` | `#0d1117` | sidebar, sheets, record tiles |
| `--surface` | `#121821` | cards, segmented control track |
| `--raised` | `#18202b` | hover rows, bar tracks |
| `--raised-2` | `#1c2530` | active segment, code chips |
| `--row-hi` | `#141b24` | highlighted (overhead) row |
| `--line` | `#222b37` | borders, dividers |
| `--line-2` | `#2a3542` | gauge track, sheet handle, pill borders |
| `--bar-idle` | `#2c3946` | histogram bars (live) |
| `--bar-future` | `#28313d` | histogram bars after playhead (replay) |
| `--text` | `#e8edf2` | primary text |
| `--text-2` | `#b9c2cc` | secondary values |
| `--muted` | `#8d9bab` | labels, units (≥4.5:1 on bg) |
| `--dim` | `#5f6c7b` | column headers, tick labels only |
| `--alt-low` | `oklch(0.74 0.15 30)` | altitude < 10,000 ft (coral) |
| `--alt-mid` | `oklch(0.82 0.14 80)` | altitude < 25,000 ft (amber); also "peak/busiest" highlight |
| `--alt-high` | `oklch(0.80 0.11 215)` | altitude ≥ 25,000 ft (cyan); also general accent / links |
| `--live` | `oklch(0.80 0.15 155)` | Live mode only (dot, NOW pill, playhead in live) |
| `--replay` | `oklch(0.76 0.13 295)` | Replay mode only (segment, play button, past bars) |
| `--replay-text` | `oklch(0.85 0.09 295)` | text on replay tints |

Tints: live pill bg `oklch(0.80 0.15 155 / 0.14)`; live dot halo `box-shadow: 0 0 0 4px oklch(0.80 0.15 155 / .18)`; replay segment bg `oklch(0.76 0.13 295 / 0.18)`, border `/ 0.5`; replay map wash `rgba(130,100,220,0.07)` overlay; floating panels `rgba(13,17,23,0.88–0.92)`.

Map overlay (dark): range ring stroke `rgba(150,170,200,0.16)`, ring labels `#6f7f92`, home marker `#e8edf2`.

**Rule:** green is never used for home/location any more — it only means "live". Home is a neutral white crosshair.

### Colours — light (secondary)
bg `#eef1f4`, cards `#ffffff`, inset cells `#f5f7f9`, dividers `#dfe4ea`, handle `#d3d9e0`, text `#11161d`, muted `#55626f`. Altitude ramp darkened: low `oklch(0.58 0.17 30)`, mid `oklch(0.62 0.14 65)`, high `oklch(0.55 0.12 235)`; live `oklch(0.60 0.15 155)`. Range rings `rgba(40,60,90,0.2)`. Borders → shadows: floating pill `0 2px 10px rgba(20,30,50,.12)`, sheet `0 -6px 24px rgba(20,30,50,.10)`. Switch via `prefers-color-scheme` + manual override.

### Typography
Google Fonts: `Barlow` 400/500/600, `Barlow Condensed` 500/600/700, `JetBrains Mono` 400/500 (code chips + technical strings only).
- **Every updating number:** `font-variant-numeric: tabular-nums`.
- Wordmark "OVERHEAD": Barlow Condensed 600, 22px (desktop) / 17px (mobile), letter-spacing .2em / .18em.
- Section/field labels (DIST, ALT, LOOK UP…): Barlow Condensed 600, 11–14px, letter-spacing .14em, uppercase, `--muted`.
- Callsigns: Barlow Condensed 600, letter-spacing .04em — hero 52px (desk) / 42px (mobile), list rows 19px / 18px.
- Readout values: Barlow 500 — hero 24px / 21px with units 14px/13px in `--muted`.
- List values: Barlow 400, 16px (desk) / 15px (mobile).
- Replay clock: Barlow 500, 60px desk (HH:MM:SS) / 46px mobile (HH:MM), line-height .95.
- Stats: page title Barlow Condensed 600 56px / 40px; headline numbers Barlow 500 96px, letter-spacing -.02em; record values 40px; chart titles Barlow Condensed 600 20px.
- Body/secondary: Barlow 14–16px.

### Radii
Phone frame (mock only) 44px · sheet top 24px · cards 14–16px · segmented control 10px / segments 7px · inset readout grid 10px · rows 8px · pills/round buttons 99px / 50% · tags 3–4px · bars 1–3px.

### Spacing
Sidebar padding 24px horizontal; card padding 20px; row padding 8px×12px (desk), min-height 48px (mobile); floating map controls inset 20–24px; stats page padding 40×48px, tile gap 16px. All hit targets ≥ 44px on mobile.

---

## Screens

### 1. Live Map — desktop (≥ ~900px)
Grid: `372px | minmax(0,1fr)`, full viewport height.

**Sidebar** (`--sidebar`, right border `--line`, flex column):
1. Header row: "OVERHEAD" wordmark left, "Stats →" link right (15px `--muted`). Padding 22/24/18.
2. **Mode switch** (segmented, 2 equal columns): track `--surface` + 1px `--line`, 4px padding, radius 10. Segments 36px tall. Active "Live": bg `#1c2530`, 600, 8px `--live` dot with halo. Inactive "Replay": `--muted`, 500.
3. Status line: "9 aircraft · live" 14px `--muted`.
4. **Look-up card** (`--surface`, 1px `--line`, radius 14, padding 20, gap 16) — shows the contact with the **highest elevation angle** (not nearest):
   - Label row: "LOOK UP" left; right "{16-pt compass bearing} · {elev}° UP" in `--text`.
   - Callsign (52px) + airline name (15px `--muted`) on the left; **elevation gauge** right: 72×72 SVG, quarter-arc track `M68 66 A62 62 0 0 0 6 4` + baseline, stroke `--line-2` 2px; needle line from (6,66) length 62, rotated `-elev` deg around (6,66), stroke = altitude colour 2.5px, 4px dot at tip.
   - 3-cell readout grid (1px gaps on `--line` = hairline dividers, radius 10): DIST `{km}` km · ALT `{ft}` ft (value in altitude colour) · ELEV `{deg}°`.
5. Column header row: grid `minmax(0,1fr) 56px 76px 40px`, gap 10: "NEAREST FIRST | KM | FT | ELEV" (12px condensed, `--dim`, right-aligned numbers).
6. **Contacts list** (scrollable, `overflow-y:auto`, hidden scrollbar), sorted by ground distance ascending. Row = same grid, padding 8×12, radius 8, hover bg `--raised`:
   - Col 1: 14px chevron SVG rotated to heading, filled altitude colour; callsign (19px) on line 1; line 2 (12px `--muted`): optional **OVERHEAD** tag (when elev ≥ 40°: 11px condensed 600, bg = altitude colour, text `#0a0d12`, padding 0 4px, radius 3) followed by airline name.
   - KM: 1 decimal if < 10 km, else integer.
   - FT: thousands separator, altitude colour, followed by a 12px fixed-width vertical-trend glyph `↑` / `↓` / blank in `--muted`.
   - ELEV: integer degrees, `--text-2`.
   - Overhead rows get bg `--row-hi`.
7. Footer (border-top): altitude legend — 10px swatches, "<10k ft", "<25k", "≥25k".

**Map pane:**
- Leaflet map, home centred. Range rings at **5 / 10 / 20 / 30 km** (`L.circle` in metres, no fill, ring stroke colour, 1px) with small labels "5 km" etc at the ring top (11px, letter-spacing .06em, bg = map bg). Faint N–S / E–W crosshair through home.
- Home marker: 16px ring, 2px `--text` border, 4px centre dot.
- **Aircraft marker** (`L.divIcon`): 20px chevron SVG `points="12,1 21,22 12,17 3,22"`, fill = altitude colour, 1.5px stroke in map bg colour (keeps it separable from tiles), CSS `rotate(heading)`. If elev ≥ 40°: 34px ring around it, 1.5px altitude colour @ 55% opacity.
- **History dots**: last 6 positions as 4px circles in altitude colour, opacity 0.6 → ~0.1 (newest → oldest).
- **Data block label** (toggleable): offset 14px right / −18px up, 1px left rule in altitude colour, 12px Barlow Condensed: line 1 callsign (600, `--text`), line 2 flight level `FL` (alt/100, zero-padded to 3) + trend arrow, in altitude colour.
- Top-right control stack (44px squares, `--surface`, 1px `--line`, radius 10, gap 8): "N" (reset north), +/− zoom, recentre-on-home.
- **Timeline strip** (bottom, inset 24px, height 68, bg `rgba(13,17,23,.88)`, 1px `--line`, radius 14), grid `auto | 1fr | auto`, gap 18:
  - Left label "LAST 24H" + "drag to rewind" (12px `--dim`).
  - Histogram: 96 bars (15-min buckets, oldest → now), gap 2px, `--bar-idle`, last bar `--live`; tick labels 18:00/00:00/06:00/12:00 (10px `--dim`). 2px `--live` playhead at the right edge.
  - Right: "● NOW" pill (36px, live tint, Barlow Condensed 600 14px, .12em).

### 2. Live Map — mobile (< ~900px)
- Map is full-screen. **No stacked sidebar.**
- Floating top bar (top = safe-area + ~10px, inset 16): pill (44px) with wordmark + live dot + aircraft count; right 44px round "stats" button (3-bar glyph).
- Timeline strip floats just above the sheet: 44px tall, 48 bars + "NOW" pill.
- **Bottom sheet** (`--sidebar`, top border, radius 24 top), handle 40×5. Two snap points:
  - **Peek:** look-up card (label row, callsign 42px + airline, 3-cell readout grid) + "8 more · nearest first ↑ swipe".
  - **Expanded** (sheet top ≈ 35% of viewport): heading "9 aircraft nearest first", rows grid `minmax(0,1fr) 44px 64px 34px`, min-height 48, callsign ellipsised.
  - Implement with a scroll container + `scroll-snap-type: y mandatory`; pad bottom with `env(safe-area-inset-bottom)`.

### 3. Replay — desktop
Same grid as Live. Mode is signalled by colour: everything green becomes violet.
- Segmented control: "Replay" active (replay tint bg, `--replay-text`), "Live" inactive with hollow dot.
- Look-up card is replaced by a **clock card**: "REPLAYING · SAT 3 OCT" (replay text colour), clock `HH:MM:SS` 60px, "{relative time, e.g. 3 h 28 m ago} · N aircraft in view", then window chips **1h / 6h / 24h** (3 equal columns, 36px, radius 8; active = replay tint + border).
- List header "IN VIEW AT THIS MOMENT"; rows: 8px altitude-colour dot, callsign, altitude right.
- Map: faint violet wash overlay. Recorded tracks: **flown portion** = dots every ~1.5 km brightening toward the aircraft (opacity ~0.15 → 0.75, 3px); **remaining portion** = sparse 2px dots @ 0.18. Aircraft chevrons at the interpolated position.
- **Expanded timeline** (bottom, inset 24, padding 16/20/14, radius 16, bg `rgba(13,17,23,.92)`):
  - Controls row: 48px round play/pause (bg `--replay`, glyph `▶` / `❚❚` in `#0a0d12`); speed pill (36px, min-width 56, 1px `--line-2`) cycling **1× → 5× → 20×** on tap; hint "tap to change speed"; right-aligned "● BACK TO LIVE →" pill (live tint).
  - Histogram 64px: 72 bars across the window; bars before the playhead `--replay`, after `--bar-future`. Ticks every 10 min (1h), 1 h (6h), 4 h (24h). Playhead: 2px `--text` line with 12px knob and `0 0 0 4px` replay halo.

### 4. Replay — mobile
Map full-screen with violet wash; top-left "REPLAY" pill (violet border/text); top-right "● LIVE" pill (returns to live). Bottom panel: clock `HH:MM` 46px + relative time; window chips (44px); 44px histogram with playhead; row with 52px play button, 44px speed pill, "N in view".

### 5. Stats — desktop (centred column, max ~1200px)
- Header: "← Map" link (15px `--muted`), "Stats" title 56px; right "Logging since {date}".
- Row 1 (2 columns, gap 16): **Seen today** and **Seen all-time** headline tiles (`--surface`, radius 16, padding 24/28): label, 96px number, inline caption ("contacts since midnight" / "+N unique aircraft").
- Row 2 (4 columns): **record tiles** (`--sidebar`, radius 14, padding 20, gap 14): label + 40px glyph top-right, 40px value, caption "{callsign} · {date}".
  - Closest pass — two concentric rings with a coral dot near centre.
  - Farthest — rings with a cyan dot at the outer edge.
  - Highest altitude — 3px vertical gradient bar (cyan→amber→coral, top→bottom) with a white tick at the top; value in `--alt-high`.
  - Busiest hour — mini 24-bar strip, busiest bar amber; value in `--alt-mid`; caption "31 contacts · to 18:00".
- Row 3 (`520px | 1fr`):
  - **Contacts per hour (last 24h)** — radial 24-hour clock, 440px square. Night shading: circle with `conic-gradient(rgba(120,140,200,.10) 0 90deg, transparent 90deg 315deg, rgba(...) 315deg 360deg)` (21:00–06:00). Inner disc 160px diameter. 24 bars, 14px wide, radius 3, starting 86px from centre, length = count/max × 118px, rotated `hour × 15deg` (00 at top, clockwise). Bars `--alt-high`; busiest hour `--alt-mid`. 2px `--live` "now" needle. Hour labels 00/06/12/18. Centre: "PEAK", hour (34px amber), "N contacts". Legend: night, now. Build as inline SVG (paths/rects rotated around centre) in production.
  - **Top airlines** — rows grid `52px 150px 1fr 64px 44px`: ICAO prefix in JetBrains Mono chip (`#1c2530`), name, 14px bar on `--raised` (leader in `--alt-high`, others `--alt-high` @ 60%, "Private / GA" `#3a4656`), count, share %. Airline derived from callsign ICAO prefix; non-airline callsigns grouped as "Private / GA" (shown last).

### 6. Stats — mobile
Stacked: "← Map" (44px target), title 40px; 2-up Today/All-time tiles (44px numbers; abbreviate all-time "48.2k"); 2×2 records grid with hairline dividers; radial chart at 320px (bars 10px wide from 62px radius, max length 82px); top 5 airlines as label row + 8px bar.

---

## Interactions & Behaviour
- **One continuous timeline (core concept).** Live = playhead pinned to NOW. Dragging the playhead / tapping anywhere on the histogram **enters Replay** at that time. "NOW" / "Back to live" springs the playhead to the right edge and returns to Live. The segmented control is a shortcut for the same state.
- **Mode transition:** accent colours crossfade green ↔ violet over 250 ms ease; violet map wash fades in; live markers fade out while recorded tracks draw in (~400 ms). Strip expands from 68px to the full replay panel.
- **Play/pause** toggles playback; reaching the end of the window stops playback (or offers to go Live). **Speed** cycles 1×/5×/20× (multiplier on real time). **Window chips** rescale the histogram and tick spacing; keep the playhead time if it is within the new window, else clamp.
- **Scrub:** pointer events on the histogram; playhead follows the pointer and the clock and map update live. Optional: `navigator.vibrate(5)` on each hour boundary (Android only).
- **Live marker motion:** CSS `transition: transform 1s linear` on marker position/rotation between updates so planes glide instead of jumping.
- Row hover (desktop) → `--raised`; clicking a row or marker selects it (pans/highlights; shows the data block if labels are off).
- Mobile sheet: swipe between peek/expanded; tapping a list row collapses to peek and shows that aircraft in the look-up card.
- Respect `prefers-reduced-motion`: no gliding, no crossfades, instant snaps.

### Derived values
- Elevation angle = `atan(alt_ft × 0.0003048 / ground_dist_km)` in degrees.
- Overhead = elev ≥ 40°.
- Look-up subject = max elevation among current contacts.
- Bearing → 16-point compass (`N, NNE, …, NNW`).
- Flight level = `round(alt/100)` zero-padded to 3.
- Altitude colour: < 10,000 low · < 25,000 mid · else high.

## State
`mode` ('live' | 'replay'), `playheadTime`, `playing`, `speed` (1|5|20), `window` ('1h'|'6h'|'24h'), `selectedCallsign`, `labelsOn`, `theme` ('dark'|'light'|'auto'), mobile `sheetSnap` ('peek'|'expanded'). Data: live contacts (poll/WebSocket), histogram buckets per window (contacts per 15 min for the live strip, 72 buckets for the replay window), track points for the replay window, stats aggregates.

## Leaflet / implementation notes
- **Dark tiles:** apply `filter: invert(1) hue-rotate(180deg) brightness(.75) saturate(.35)` to `.leaflet-tile-pane` in dark theme (no new dependency); none in light. Alternative: CARTO dark basemap (OSM data, attribution required).
- Markers: `L.divIcon` with inline SVG; history dots `L.circleMarker`; rings `L.circle`; replay tracks `L.circleMarker` dot runs (or a `L.polyline` with `dashArray` as a cheaper fallback).
- Charts: hand-rolled inline SVG as today; the radial chart is 24 `<rect>`s with `transform="rotate(h*15 cx cy)"`.
- PWA: set `<meta name="theme-color" content="#0a0d12">` (light: `#eef1f4`); use safe-area insets for the floating top bar and sheet.
- No new libraries are required for anything in this handoff.

## Assets
No raster assets. All glyphs are simple inline SVG (chevron, gauge arc) or CSS shapes. Fonts from Google Fonts.

## Files
- `Overhead Redesign.dc.html` — full design canvas: directions (1a/1b/1c), Live desktop + mobile (peek, expanded), Replay desktop + mobile (interactive), timeline concepts T1–T3, Stats desktop + mobile, light theme, build notes. The logic class at the bottom contains the data shapes and derived-value formulas.
- `Scope.dc.html` — map stand-in: ring geometry, marker, history-dot and replay-track rendering, and per-theme tokens (`THEMES` object).
- `support.js` — mock runtime only; open the HTML files in a browser to view. Not for production.
