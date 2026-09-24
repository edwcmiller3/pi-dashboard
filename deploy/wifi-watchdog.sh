#!/bin/sh
# Wi-Fi reconnect watchdog: kick wlan0 back to connecting only when it's genuinely
# down, leaving a healthy or in-progress link alone. Runs as wifi-watchdog.service.
#
# Two traps this avoids (both bit a live rebuild - hidden SSID, slow join):
#  - STATE source: `device show` GENERAL.STATE reads "100 (connected)", so a
#    "^connected" anchor never matches even when connected, and the kick fired every
#    cycle. `device status` STATE is the plain word, so the match is exact.
#  - never kick while state is `connecting*`: forcing `device connect` on an
#    in-progress association tears it down mid-associate (local deauth, reason 3),
#    which on a slow hidden-SSID join loops forever and never completes.
while true; do
  state=$(nmcli -t -f DEVICE,STATE device status 2>/dev/null | sed -n 's/^wlan0://p')
  case "$state" in
    connected|connecting*) ;;                            # up, or mid-join - leave alone
    *) nmcli device connect wlan0 2>/dev/null || true ;; # down - kick it
  esac
  sleep 30
done
