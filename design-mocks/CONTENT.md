# Shared content spec for design mocks

Every mock renders EXACTLY this content so designs can be compared apples-to-apples.
Same information architecture as the real dashboard; layout/visual treatment is free.

## Canvas
- Fixed 1280 × 800 px canvas (the kiosk's effective viewport), centered on the page
  body with a neutral surround so it reads like a framed screen.
- Self-contained single HTML file: inline CSS, inline JS (if any), no build step.
  Google Fonts links are permitted (mock-only; prod self-hosts fonts).
- No blur/backdrop-filter is required, but the real device has a thermal budget -
  heavy filters were reverted in prod. Prefer cheap effects.

## Regions (all must be present)
1. **Clock + date** - 2:46 PM · Saturday, July 11
2. **Current conditions** - 82° Partly cloudy (daytime), H 88° / L 71°,
   Feels like 85°, Rain 15%, Humidity 52%, Wind 7 mph, Sunrise 5:47a, Sunset 8:29p
3. **4-day forecast** (future days only):
   - Sunday - Clear, 90° / 72°, no precip line
   - Monday - Thunderstorm, 84° / 70°, 65% precip
   - Tuesday - Light rain, 78° / 66°, 45% precip
   - Wednesday - Partly cloudy, 81° / 68°, no precip line
4. **Agenda ("Upcoming")** - two columns or equivalent:
   - **Today · Jul 11**: holiday/observance pill "Summer Festival";
     ALL DAY - Cabin trip; "+5 earlier" roll-off marker;
     1:30p Focus block ← THIS is the in-progress "next up" item, visually highlighted;
     3:30p School pickup; 4:45p Vet appointment; 5:30p Swim practice;
     7:00p Dinner reservation; "+2 more" overflow marker
   - **Sunday · Jul 12**: ALL DAY - Cabin trip; 9:00a Farmers market; 2:00p Bike ride
   - **Monday · Jul 13**: holiday pill "Independence Day";
     11:00a Neighborhood parade; 8:30p Fireworks picnic
   - "+2 more days" overflow marker at the end
5. **Status footer** - WEATHER ok · CALENDAR ok · "Updated 2:46 PM"

## Weather icons
No icon font available. Use inline SVG, unicode glyphs, or typographic treatment -
whatever suits the design direction. Condition text must remain readable.

## Legibility constraints (it's a wall display read from across a room)
- Clock and current temp are the loudest elements.
- Forecast highs and event titles readable at a glance.
- Don't shrink body text below ~14px equivalent at 1280×800.

## Admin screen (admin mocks only)

The admin mocks (`admin-*.html`) render the Admin screen in each layout's idiom.
It is theme-aware AND layout-skinned (one admin per layout). Three panels + a
top-left back arrow. Every admin mock renders EXACTLY the values below so the
mocks compare apples-to-apples, same as the dashboard fixture above.

### Config panel — the three editable knobs
Each knob shows its current value and a set of selectable options (no free-text;
the real picker is driven by the server's `_available_slugs`). Changes stage,
then a single **Apply** writes `.env` + restarts. Current (live) value is marked.

- **Layout** — current: `classic`. Options: classic, hud, swiss-mono,
  paper-editorial, neo-brutalist, soft-scandi.
  (Each admin mock marks ITS OWN layout as current, e.g. the neo-brutalist mock → `neo-brutalist`.)
- **Theme** — current: `default`. Options: default, catppuccin, gruvbox, nord, synthwave.
- **Icon pack** — current: `weather-icons`. Options: weather-icons, meteocons,
  meteocons-flat, meteocons-line, meteocons-mono.

### Device health panel — two fixture variants
Pi-only fields (temperature, throttle) read "unavailable" off-Pi; mocks show the
on-Pi values. Render the **nominal** set as the primary; show the **degraded**
set as a secondary state frame.

| Metric        | Nominal                        | Degraded                                              |
|---------------|--------------------------------|-------------------------------------------------------|
| CPU           | 22%                            | 96%                                                   |
| RAM           | 1.4 / 3.8 GB                   | 3.6 / 3.8 GB                                          |
| Temperature   | 48.3 °C                        | 82.4 °C                                               |
| Disk (SD)     | 4.1 / 29 GB                    | 27.3 / 29 GB                                          |
| Uptime        | 8h 46m (since 06:00 reboot)    | 8h 46m                                                |
| Host          | raspberrypi                    | raspberrypi                                           |
| Throttle      | No throttling (`0x0`)          | Under-voltage + Throttled, now & earlier (`0x50005`)  |
| Network       | 192.168.1.42 /24 · wlan0       | 192.168.1.42 /24 · wlan0                              |

Throttle is shown as **decoded flags**, never raw hex alone. `0x50005` decodes to
under-voltage (now + occurred) and throttled (now + occurred).

### Device actions panel
- **Restart dashboard** — reloads the display, no reboot. No-root user-service restart.
- **Reboot Pi** — full restart, ~40s dark. Both require an explicit on-screen confirm.

### States to depict (storyboard frames)
1. Resting — nominal health, nothing staged, Apply inactive.
2. Config staged — one knob changed (Theme → `nord`), Apply active.
3. Reboot confirm — dialog over a dimmed admin screen.
4. Rebooting — terminal "rebooting…" state (screen goes dark until the Pi returns).
5. Device health — degraded variant.
