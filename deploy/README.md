# deploy/ — Pi system configuration

Version-controlled home for the Pi's system-config files, so production setup is
`git pull` + a documented install step rather than hand-editing files on the box.

Some files are still stubs (content is spike-dependent and lands in Phase 8):

| File | Installs to | Status | Notes |
|------|-------------|--------|-------|
| `kiosk.service` | `~/.config/systemd/user/` | stub (Phase 8) | Promotes the Phase-0 labwc user service; `enable-linger`. |
| `labwc/rc.xml` | `~/.config/labwc/` | **authored (Phase 7)** | `<touch mouseEmulation="no" />` + a `HideCursor` keybind. No `<calibrationMatrix>` (0.2 aligned). **Do not** set `<autoEnableOutputs>no</autoEnableOutputs>` (0.4). |
| `50unattended-upgrades` | `/etc/apt/apt.conf.d/` | stub (Phase 8) | Auto-reboot ~03:00 (inside the 1a-6a window). |

**`blackout.{service,timer}` — dropped (Phase 7).** Spikes 0.4 + 0.5 ❌ ruled out
every hardware blackout (no DDC/CI, no `/sys/class/backlight`, and signal-off
can't hold the panel dark). The nightly 1a–6a blackout is now an **app-side
wall-clock CSS overlay** in `static/` (`#blackout`, toggled by `app.js`'s
`inBlackout`), so there is no systemd timer to install — the schedule lives in
the frontend. It's wall-clock-driven on purpose so the Phase-8 03:00 reboot
(inside the window) comes back to black, not the bright dashboard.

## Install (filled in Phase 8)

```sh
# placeholder — exact paths/commands documented when content lands
```
