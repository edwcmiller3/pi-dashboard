# deploy/ — Pi system configuration

Version-controlled home for the Pi's system-config files, so production setup is
`git pull` + a documented install step rather than hand-editing files on the box.

**These are stubs.** Real content is authored later, because it's spike-dependent
(Phase 0 results) and lands in Phases 7-8:

| File | Installs to | Authored in | Notes |
|------|-------------|-------------|-------|
| `kiosk.service` | `~/.config/systemd/user/` | Phase 8 | Promotes the Phase-0 labwc user service; `enable-linger`. |
| `labwc/rc.xml` | `~/.config/labwc/` | Phase 7 | `mouseEmulation="no"`, `HideCursor`. No `<calibrationMatrix>` (0.2 aligned). **Do not** set `<autoEnableOutputs>no</autoEnableOutputs>` (0.4). |
| `blackout.{service,timer}` | `/etc/systemd/system/` | — | **Likely dropped.** 0.4 + 0.5 ❌ → blackout is an app-side wall-clock CSS overlay (Phase 7), not a systemd timer. Kept as a stub pending the Phase-7 call. |
| `50unattended-upgrades` | `/etc/apt/apt.conf.d/` | Phase 8 | Auto-reboot ~03:00 (inside the 1a-6a window). |

## Install (filled in Phase 8)

```sh
# placeholder — exact paths/commands documented when content lands
```
