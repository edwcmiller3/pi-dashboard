# deploy/ — Pi system configuration

Version-controlled home for the Pi's system-config files, so production setup is
`git pull` + a documented install step rather than hand-editing files on the box.

## Storage / root model (decided 2026-06-30)

**SD card, normal read-write root** — accepted SD-wear risk, mitigated below.
NVMe-RW was the lower-wear option but we stayed on SD for this build. The two
biggest continuous writers are addressed directly: journald is kept in RAM
(`journald.conf`, `Storage=volatile`) and Chromium's cache/profile are routed to
tmpfs (flags in `chromium-kiosk.service`).

**Swap — disable only the SD-backed swapfile, keep zram.** The wear concern is
`dphys-swapfile`, a swap *file on the SD card*. Disable it if present:

```sh
sudo systemctl disable --now dphys-swapfile.service   # 8 GB Pi 5, light kiosk -> no swapfile
sudo dphys-swapfile uninstall 2>/dev/null || true
```

If the first command reports **`Unit dphys-swapfile.service does not exist`**,
that's fine — newer Pi OS images don't install it, so there's no SD-backed swap to
turn off. The goal is already met; continue.

Do **not** disable zram swap (`swapon --show` listing `/dev/zram0`). zram is
*compressed swap in RAM* — it never writes to the SD card, so it costs zero wear
and gives a useful OOM cushion under a memory spike. Leave it enabled.

A read-write root (not read-only overlayfs) is what makes `unattended-upgrades`
viable — on an overlayfs RO root, apt installs land in the tmpfs upper layer and
vanish on reboot, so that build would update by re-imaging instead.

## Files

| File | Installs to | Scope | Purpose |
|------|-------------|-------|---------|
| `pi-dashboard.service` | `~/.config/systemd/user/` | user | FastAPI backend (uvicorn) on `127.0.0.1:8000`. |
| `kiosk.service` | `~/.config/systemd/user/` | user | labwc compositor (the Wayland session). |
| `chromium-kiosk.service` | `~/.config/systemd/user/` | user | Chromium kiosk, pinned flag set, `Restart=always`. |
| `chromium-reload.{service,timer}` | `~/.config/systemd/user/` | user | Nightly 04:00 browser reload (deploy pickup + memory hygiene). |
| `labwc/rc.xml` | `~/.config/labwc/` | user | `mouseEmulation="no"` + `HideCursor` (Phase 7). |
| `labwc/autostart` | `~/.config/labwc/` | user | Nudges the virtual pointer at session start so the cursor auto-hides via the page's CSS `cursor:none` (no touch needed). Requires `wlrctl`. |
| `journald.conf` | `/etc/systemd/journald.conf.d/00-kiosk-volatile.conf` | system | Logs in RAM only — zero SD wear. |
| `getty-autologin.conf` | `/etc/systemd/system/getty@tty1.service.d/autologin.conf` | system | tty1 autologin + quiet boot (`--noclear --noissue`). |
| `50unattended-upgrades` | `/etc/apt/apt.conf.d/` | system | Security upgrades + auto-reboot 03:00 (inside blackout). |
| `20auto-upgrades` | `/etc/apt/apt.conf.d/` | system | Enables the apt periodic timers that run the above. |

**`blackout.{service,timer}` — dropped (Phase 7).** Spikes 0.4 + 0.5 ❌ ruled out
every hardware blackout. The nightly 1a–6a blackout is an **app-side wall-clock
CSS overlay** (`static/`, `app.js` `inBlackout`), wall-clock-driven so the 03:00
reboot comes back to black, not the bright dashboard.

## Install

Assumes the repo is at `~/pi-dashboard` and `uv` is at `~/.local/bin/uv`.

### Prerequisites (first time on the Pi)

These are NOT in git, so a fresh box needs them before the steps below:

- **`git` + `uv` installed** (Phase 0 installed git; install uv if absent):
  `command -v uv || curl -LsSf https://astral.sh/uv/install.sh | sh`
- **`wlrctl` installed** (for the `labwc/autostart` cursor-hide; not in git):
  `sudo apt install -y wlrctl`
- **The repo cloned to `~/pi-dashboard`** (the unit files hardcode this path):
  `git clone <repo-url> ~/pi-dashboard` (the "first pull" is really a clone).
- **`.env` created** — it is git-ignored (holds the secret, PII-bearing
  `PROTON_ICS_URL`) so it never arrives via `git pull`. Without it the app still
  runs (weather on defaults + holidays), but shows **no personal calendar events**:
  ```sh
  cp ~/pi-dashboard/.env.example ~/pi-dashboard/.env
  # then edit .env: set PROTON_ICS_URL to a CURRENT Proton "Full view" link
  # (the 0.D1 test links were to be revoked) and WEATHER_LAT/WEATHER_LON.
  ```

### 1. App + backend service

```sh
cd ~/pi-dashboard && git pull && uv sync
mkdir -p ~/.config/systemd/user ~/.config/labwc
cp deploy/pi-dashboard.service deploy/kiosk.service \
   deploy/chromium-kiosk.service \
   deploy/chromium-reload.service deploy/chromium-reload.timer \
   ~/.config/systemd/user/
cp deploy/labwc/rc.xml deploy/labwc/autostart ~/.config/labwc/

systemctl --user daemon-reload
systemctl --user enable --now pi-dashboard.service kiosk.service \
   chromium-kiosk.service chromium-reload.timer
sudo loginctl enable-linger "$USER"     # start at boot without an interactive login
```

### 2. System files (root)

```sh
# Autologin + quiet boot — substitute the real kiosk user:
sudo install -Dm644 deploy/getty-autologin.conf \
  /etc/systemd/system/getty@tty1.service.d/autologin.conf
sudo sed -i "s/KIOSK_USER/$USER/" /etc/systemd/system/getty@tty1.service.d/autologin.conf

# Journald in RAM (zero SD wear):
sudo install -Dm644 deploy/journald.conf \
  /etc/systemd/journald.conf.d/00-kiosk-volatile.conf

# Unattended security upgrades + 03:00 reboot:
sudo install -m644 deploy/50unattended-upgrades deploy/20auto-upgrades \
  /etc/apt/apt.conf.d/

sudo systemctl daemon-reload
sudo systemctl restart systemd-journald
```

### 3. Quiet boot — kernel cmdline (manual, box-specific)

`/boot/firmware/cmdline.txt` is a single line with a box-specific `PARTUUID`, so
it can't be shipped wholesale. Append these tokens to the existing line (don't
add a newline) to stop kernel/console text flashing before the kiosk paints:

```
quiet loglevel=3 logo.nologo vt.global_cursor_default=0 consoleblank=0
```

And in `/boot/firmware/config.txt`, suppress the rainbow splash:

```
disable_splash=1
```

(`force_hotplug` flags are NOT needed — spike 0.0 got signal flag-free; 0.4 found
signal-off blackout non-viable, so `vc4.force_hotplug` was never required.)

### 4. Chromium wrapper noise (optional)

Pi OS `/usr/bin/chromium` injects `/etc/chromium.d/*` flags, incl. a stale
`--js-flags=--no-decommit-pooled-pages` that V8 logs as "unrecognized flag"
(cosmetic, confirmed harmless in the 0.10 soak). To silence it, clear or edit the
offending file under `/etc/chromium.d/` — left as-is by default so the distro's
other defaults aren't masked.

## Updating after a deploy (`git pull`)

Install (above) is one-time. To ship later changes, `git pull` on the Pi — but a
pull only updates files on disk; the **running processes pick up changes on their
next restart/reload**, which is what to nudge:

```sh
cd ~/pi-dashboard && git pull
```

| What changed | To see it on the Pi |
|--------------|---------------------|
| **Frontend** (`static/` — HTML/JS/CSS) | A browser reload: `systemctl --user start chromium-reload.service`. The `no-cache` static headers guarantee the reload fetches the NEW bundle (no stale `app.js`). |
| **Backend** (`app/` — Python) | `systemctl --user restart pi-dashboard.service` (production uvicorn has no `--reload`, so a pull won't repaint a running server). |
| **New/changed dependency** (`pyproject.toml`/`uv.lock`) | `uv sync`, then restart the backend. |
| **A `deploy/` unit or config file** | Re-run the relevant install step, then `systemctl --user daemon-reload` (user) / `sudo systemctl daemon-reload` (system). |

**Nothing to nudge = within a day anyway:** the nightly 04:00 Chromium reload picks
up frontend changes and the 03:00 unattended-upgrades reboot (when one fires) picks
up everything. The commands above are just for *instant* pickup after a same-day pull.

Most Phase-9 polish is frontend-only (roll-off, forecast-card detail) or reuses the
existing `POST /refresh` (the manual-refresh button), so "`git pull` + browser
reload" is usually the whole update — no install re-run, no backend restart.

## On-Pi acceptance checklist (carried into Phase 8 — run on the panel)

These need the physical Pi + panel and can't be validated from the dev Mac:

- [ ] **Deferred Phase-2 UI legibility check** (decision 2026-06-28): with the real
  dashboard on the panel at scale 1.5, eyeball the v4 layout at standing distance.
  If sizing is off it's a `rem`/type-scale tweak in `static/style.css`, not a
  redesign (v4 is locked).
- [ ] **Full blackout-cycle overnight soak** now that the overlay exists: confirm
  the screen is black across 1a–6a, the 03:00 reboot returns to black (not the
  bright dashboard), and the dashboard is back at 06:00.
- [ ] **Quiet boot**: reboot and confirm no console text / IP banner flashes
  before the kiosk paints; no stray cursor in the bare-labwc gap.
- [ ] **Respawn**: `systemctl --user kill chromium-kiosk.service` → it comes back
  fullscreen on its own (Restart=always).
- [ ] **Deploy pickup**: `git pull` a visible change, trigger the reload
  (`systemctl --user start chromium-reload.service`), confirm the new bundle
  renders (no-cache static headers + reload — no manual hard refresh needed).
- [ ] **Power under load** (0.3/0.9 follow-up): `vcgencmd get_throttled` stays
  `0x0` with the kiosk running; re-check after the soak.
