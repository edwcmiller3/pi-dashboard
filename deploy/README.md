# deploy/ — Pi system configuration

Version-controlled home for the Pi's system-config files, so production setup is
`git pull` + a documented install step rather than hand-editing files on the box.

## Storage / root model

**SD card, normal read-write root** — SD-wear risk accepted and mitigated below.
(An NVMe read-write root is lower-wear if your Pi has one; this config targets an
SD build.) The two biggest continuous writers are addressed directly: journald is
kept in RAM (`journald.conf`, `Storage=volatile`) and Chromium's cache/profile are
routed to tmpfs (flags in `chromium-kiosk.service`).

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

## Network — Wi-Fi reliability

Pi OS (Bookworm/Trixie) manages Wi-Fi with NetworkManager. Two distinct failure
modes bit this build — a boot-time join race and a mid-run drop. Both were
config, not hardware; it's worth ruling those out before blaming the Pi's radio.
Nothing app-side is involved either way — the backend's refresh loop self-heals
the moment the link is up.

### Joining a hidden SSID (boot-time)

**A hidden (non-broadcasting) SSID needs `802-11-wireless.hidden yes` on the
profile — without it the Pi joins only intermittently.** A hidden AP suppresses
its SSID in beacons, so the client can only find it by sending a *directed probe
request*, which NM sends only when the profile is flagged hidden. Unflagged, NM
falls back to passive beacon scans and association becomes a boot-time race it
loses on some reboots: the box comes up with no network (host unreachable, weather
and calendar unsynced, "Updated —"). The flag makes the join deterministic.

Run once on the Pi (Imager often doesn't set the hidden flag even when "hidden"
is ticked):

```sh
nmcli -f NAME,TYPE,DEVICE connection show     # find the Wi-Fi profile name
CN="preconfigured"                            # <- substitute the real name

sudo nmcli connection modify "$CN" 802-11-wireless.hidden yes           # probe for the hidden SSID
sudo nmcli connection modify "$CN" connection.autoconnect yes \
                                   connection.autoconnect-retries 0     # 0 = retry forever (default gives up after 4)
sudo nmcli connection modify "$CN" 802-11-wireless.powersave 2          # disable radio power-save (always-on wall panel)

sudo nmcli connection down "$CN" && sudo nmcli connection up "$CN"      # apply now; then reboot to confirm a clean boot-join
```

Consider **un-hiding the SSID** instead: a hidden name adds negligible security
(clients leak it in probes anyway) and forces trackable active scanning, which
interacts badly with the mid-run drops below.

**Where the change persists (and a netplan gotcha).** `nmcli connection modify`
writes through to whatever store backs the profile and persists across reboot —
but *which* store varies by image:

- Classic NM keyfile: `/etc/NetworkManager/system-connections/*.nmconnection`.
- netplan-backed images (profile named `netplan-*`): netplan YAML at
  `/etc/netplan/90-NM-*.yaml`, rendered to `/run/NetworkManager/system-connections/`
  at boot — the `/run` copy is regenerated each boot, so don't hand-edit it; edit
  via `nmcli` (which writes back to the YAML) or the YAML itself.

Check yours with `nmcli -g connection.filename connection show "$CN"` (or
`sudo netplan get`). Either store holds the Wi-Fi PSK, so both are root-only
(`0600`) and stay **out of git** — a re-image wipes them, which is why this is
documented here rather than shipped as a file.

### Dropping *while running* (not just at boot)

If an already-established link drops mid-session, **diagnose before buying
hardware — a mid-run drop is almost never weak signal.** First gather the basics:

```sh
iw dev wlan0 link                              # signal: > -67 dBm good, < -75 weak
iw dev wlan0 get power_save                    # must read "off"
nmcli -f SSID,BSSID,CHAN,FREQ,SIGNAL dev wifi list   # channel; is the SSID on 2.4 AND 5 GHz / multiple BSSIDs?
```

Then capture *why* it dropped — this is the load-bearing step:

```sh
sudo iw event -t                               # live: prints deauth/disassoc with reason + source
journalctl -b | grep -iE "CTRL-EVENT-DISCONNECTED|reason=|deauth"
```

The reason line splits the two root causes:

- **`disconnected (by AP) reason: N`** — the *access point* is kicking you. On a
  multi-AP / mesh network with one SSID spanning several nodes (or 2.4 + 5 GHz),
  this is typically **band/AP steering**: the AP repeatedly deauths a *stationary*
  device to "optimize" which node/band it's on, and occasionally the
  re-association stalls for minutes — the visible outage. Fixes, best first:
  (1) disable band steering / "Smart Connect" / 802.11k/v/r roaming assist on the
  router, or give each band/node its own SSID; (2) if you can't touch the AP,
  **pin the client to the strongest node's BSSID** so it snaps back to the same
  radio instead of bouncing:
  ```sh
  nmcli -f SSID,BSSID,CHAN,SIGNAL dev wifi list          # pick the strongest BSSID for your SSID
  sudo nmcli connection modify "$CN" 802-11-wireless.bssid AA:BB:CC:DD:EE:FF
  sudo nmcli connection down "$CN" && sudo nmcli connection up "$CN"
  ```
  A wall panel never roams, so pinning costs nothing — the one trade-off is that
  if that node dies the Pi won't fail over. Verify persistence as above, then
  **reboot to confirm the pin survived** (boot is exactly where this stack fails).
- **client-initiated (`locally_generated=1`), or a radar event** — the Pi left on
  its own. Usual causes: power-save re-enabling (re-check `iw ... get power_save`),
  aggressive background-scan roaming, or DFS (below).

**DFS / passive-scan channel caveat.** A hidden SSID can't be found on a
**passive-scan** channel, and on 5 GHz **DFS** channels (52–144, US regdomain) the
AP must vacate the channel for 60+ s on any radar detection — dropping every
client mid-session. If the AP sits on DFS, move it to an active-scan channel:
2.4 GHz (1–11) or 5 GHz UNII-1 (36–48) / UNII-3 (149–165). Check with
`nmcli -f SSID,CHAN,FREQ device wifi list`.

### Reconnect watchdog (when autoconnect doesn't recover)

`autoconnect-retries 0` (retry forever) keeps NM trying, but its internal backoff
can leave the interface stuck in "disconnected" for minutes — long enough to look
permanently broken after a reboot. A simple watchdog service polls every 30 seconds
and calls `nmcli device connect wlan0` whenever the device isn't connected, which
forces NM out of any backoff state. It runs as a persistent system service and
covers both boot-time failures and mid-session drops.

`wifi-watchdog.service` in this repo handles this — see [Install § 2](#2-system-files-root).

The service uses the device name (`wlan0`) rather than a connection profile name, so
it works regardless of what the profile is called and survives profile renames.

**When hardware *is* warranted.** Only if `iw dev wlan0 link` shows genuinely weak
signal (below ~-72 dBm) at the mount. Then, best first: wired Ethernet (the Pi 5
has gigabit built in) → powerline/MoCA → a wireless bridge (a small router in
client mode with real antennas, feeding the Pi over Ethernet) → a USB Wi-Fi
adapter with an external antenna (pick an in-kernel chipset, e.g. MediaTek
`mt76`, so it survives unattended kernel upgrades). A Wi-Fi HAT is rarely worth
it. At a healthy signal no adapter helps — the problem is association, not radio.

## Files

| File | Installs to | Scope | Purpose |
|------|-------------|-------|---------|
| `pi-dashboard.service` | `~/.config/systemd/user/` | user | FastAPI backend (uvicorn) on `127.0.0.1:8000`. |
| `kiosk.service` | `~/.config/systemd/user/` | user | labwc compositor (the Wayland session). |
| `chromium-kiosk.service` | `~/.config/systemd/user/` | user | Chromium kiosk, pinned flag set, `Restart=always`. |
| `chromium-reload.{service,timer}` | `~/.config/systemd/user/` | user | Nightly 04:00 browser reload (deploy pickup + memory hygiene). |
| `labwc/rc.xml` | `~/.config/labwc/` | user | `mouseEmulation="no"` + `HideCursor`. |
| `labwc/autostart` | `~/.config/labwc/` | user | Nudges the virtual pointer at session start so the cursor auto-hides via the page's CSS `cursor:none` (no touch needed). Requires `wlrctl`. |
| `wifi-watchdog.service` | `/etc/systemd/system/` | system | Polls `wlan0` every 30 s; calls `nmcli device connect` if not connected. Covers boot-time and mid-session failures that `autoconnect-retries` misses due to backoff. |
| `journald.conf` | `/etc/systemd/journald.conf.d/00-kiosk-volatile.conf` | system | Logs in RAM only — zero SD wear. |
| `getty-autologin.conf` | `/etc/systemd/system/getty@tty1.service.d/autologin.conf` | system | tty1 autologin + quiet boot (`--noclear --noissue`). |
| `50unattended-upgrades` | `/etc/apt/apt.conf.d/` | system | Security upgrades + auto-reboot 03:00 (inside the nightly blackout). |
| `20auto-upgrades` | `/etc/apt/apt.conf.d/` | system | Enables the apt periodic timers that run the above. |

**Nightly blackout is app-side, not hardware.** Cutting the panel's backlight or
HDMI signal isn't viable on this class of touchscreen — no DDC/CI or
`/sys/class/backlight` channel, and dropping the HDMI signal just triggers
re-detection a couple seconds later. So the nightly 1a–6a blackout is an app-side
wall-clock CSS overlay (`static/`, `app.js` `inBlackout`) — wall-clock-driven, so a
reboot *inside* the window comes back to black rather than the bright dashboard.

## Install

Assumes the repo is at `~/pi-dashboard` and `uv` is at `~/.local/bin/uv`.

### Prerequisites (first time on the Pi)

These are NOT in git, so a fresh box needs them before the steps below:

- **`git` + `uv` installed:**
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
  # then edit .env: set PROTON_ICS_URL to a Proton Calendar "Full view" link
  # and WEATHER_LAT/WEATHER_LON to your location.
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
# Wi-Fi reconnect watchdog:
sudo install -m644 deploy/wifi-watchdog.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now wifi-watchdog.service

# Autologin + quiet boot — substitutes the current login user into the drop-in:
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

Also empty the Pi OS IP banner drop-in — `agetty --noissue` (in
`getty-autologin.conf`) suppresses `/etc/issue` but NOT the `issue.d` drop-in that
prints "My IP address is ..." on recent Pi OS (Trixie):

```sh
sudo truncate -s 0 /etc/issue.d/IP.issue   # silences the boot-time IP banner
```

(Emptying rather than deleting: it's a packaged conffile, so the empty version is
kept across `apt`/unattended upgrades, and a reinstall restores it cleanly.)

### 4. Chromium wrapper noise (optional)

Pi OS `/usr/bin/chromium` injects `/etc/chromium.d/*` flags, which can include a
stale `--js-flags=--no-decommit-pooled-pages` that V8 logs as "unrecognized flag"
(cosmetic, harmless). To silence it, clear or edit the offending file under
`/etc/chromium.d/` — left as-is by default so the distro's other defaults aren't
masked.

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

## Verifying the install (on the panel)

These need the physical Pi + panel and can't be validated from a dev machine:

- **Boot to dashboard:** reboot and confirm the kiosk comes up fullscreen on the
  live dashboard with no console text / IP banner flashing before it paints, and no
  stray cursor in the bare-compositor gap.
- **Legibility:** eyeball the layout at standing distance. If sizing is off it's a
  type-scale tweak in `static/style.css`, not a redesign.
- **Nightly blackout:** confirm the screen is black across 1a–6a, that a reboot
  *inside* the window returns to black (not the bright dashboard), and that the
  dashboard is back at 06:00.
- **Crash recovery:** `systemctl --user kill chromium-kiosk.service` → Chromium
  comes back fullscreen on its own (`Restart=always`).
- **Deploy pickup:** `git pull` a visible change, trigger the reload
  (`systemctl --user start chromium-reload.service`), and confirm the new bundle
  renders (no-cache static headers + reload — no manual hard refresh needed).
- **Thermals under load:** `vcgencmd get_throttled` stays `0x0` with the kiosk
  running.
