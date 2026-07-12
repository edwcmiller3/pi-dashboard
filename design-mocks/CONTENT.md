# Shared content spec for design mocks

Every mock renders EXACTLY this content so designs can be compared apples-to-apples.
Same information architecture as the real dashboard; layout/visual treatment is free.

## Canvas
- Fixed 1280 × 800 px canvas (the kiosk's effective viewport), centered on the page
  body with a neutral surround so it reads like a framed screen.
- Self-contained single HTML file: inline CSS, inline JS (if any), no build step.
  Google Fonts links are permitted (mock-only; prod self-hosts fonts).
- No blur/backdrop-filter is required by the mock, but note: the real device has a
  thermal budget — heavy filters were reverted in prod. Prefer effects that are cheap.

## Regions (all must be present)
1. **Clock + date** — 2:46 PM · Saturday, July 11
2. **Current conditions** — 82° Partly cloudy (daytime), H 88° / L 71°,
   Feels like 85°, Rain 15%, Humidity 52%, Wind 7 mph, Sunrise 5:47a, Sunset 8:29p
3. **4-day forecast** (future days only):
   - Sunday — Clear, 90° / 72°, no precip line
   - Monday — Thunderstorm, 84° / 70°, 65% precip
   - Tuesday — Light rain, 78° / 66°, 45% precip
   - Wednesday — Partly cloudy, 81° / 68°, no precip line
4. **Agenda ("Upcoming")** — two columns or equivalent:
   - **Today · Jul 11**: holiday/observance pill "Summer Festival";
     ALL DAY — Cabin trip; "+5 earlier" roll-off marker;
     1:30p Focus block ← THIS is the in-progress "next up" item, visually highlighted;
     3:30p School pickup; 4:45p Vet appointment; 5:30p Swim practice;
     7:00p Dinner reservation; "+2 more" overflow marker
   - **Sunday · Jul 12**: ALL DAY — Cabin trip; 9:00a Farmers market; 2:00p Bike ride
   - **Monday · Jul 13**: holiday pill "Independence Day";
     11:00a Neighborhood parade; 8:30p Fireworks picnic
   - "+2 more days" overflow marker at the end
5. **Status footer** — WEATHER ok · CALENDAR ok · "Updated 2:46 PM"

## Weather icons
No icon font available. Use inline SVG, unicode glyphs, or typographic treatment —
whatever suits the design direction. Condition text must remain readable.

## Legibility constraints (it's a wall display read from across a room)
- Clock and current temp are the loudest elements.
- Forecast highs and event titles readable at a glance.
- Don't shrink body text below ~14px equivalent at 1280×800.
