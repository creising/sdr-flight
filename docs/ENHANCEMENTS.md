# Feature enhancements — backlog

Ideas captured for later. Not scheduled; pick up any time.

## ATC airband audio ("listen to the radio") 🎧
Receive and stream live aircraft/ATC **voice** from the SDR.
- **Band:** VHF airband ~118–137 MHz, **AM**. The RTL-SDR covers it (24 MHz–1.7 GHz).
- **Scope:** an "ATC audio" panel in the app — pick a frequency (tower / ground / approach / center / ATIS, from a small preset list for the Asheville/AVL + ATL-center area), demodulate on mercury with `rtl_fm -M am -f <freq>`, stream the audio to the browser. Optionally **auto-suggest the likely frequency** for whatever's overhead (from position/phase of flight).
- **Nuance:** voice is per-**frequency** (shared ATC), not per-aircraft — you hear everyone on that channel. No hex→frequency link from the SDR alone.
- **Requires:** a **second RTL-SDR dongle** on mercury (~$25–30), so ADS-B on 1090 MHz keeps running on the first. Ideally a VHF airband antenna too (the 1090 antenna is the wrong length for 118 MHz).
- **Legal:** receiving unencrypted ATC is legal in the US (don't rebroadcast for certain uses); some countries restrict it.
- **Status:** backlog — waiting on a 2nd dongle.

## Full airline names
Show "American Airlines" instead of the IATA/ICAO code in the selected card. Needs an
offline ICAO/IATA → airline-name table (small bundled CSV) or an AeroAPI /operators lookup.

## Phase 4 — overhead alerts + Web Push PWA
Push a notification to the phone when a plane matches a rule (overhead / low pass / rare type /
emergency squawk). Installable PWA + Web Push (VAPID), native Apple notifications. (Original
roadmap Phase 4.)

## International aircraft registry
FAA registry is US (N-numbers) only. Add a fallback for non-US aircraft (e.g. the OpenSky
aircraft database CSV, hex → registration/type) so make/model shows for foreign airframes.

## Nice-to-haves
- Surface more decoded fields inline (autopilot **target altitude**, friendly **category**
  labels like "Large/Heavy/Rotorcraft") — all already available in the RAW ADS-B dialog.
- Draw the selected flight's route (origin → plane → destination) on the map.
