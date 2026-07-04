#!/bin/sh
# Nightly pre-halt — clean poweroff at 01:00, five minutes before the smart plug
# cuts wall power at 01:05 (plug schedule is on-device; see README "Nightly
# power-off window"). Halt-then-cut keeps the nightly cycle filesystem-safe:
# the plug only ever hard-cuts a board that is already off.
#
# The RTC wakealarm is the plug-fails backup: if the plug never cuts power, the
# Pi 5's RTC boots the halted board at 06:00 anyway. On the normal path the
# alarm is moot — wall power is gone (no RTC battery), and the plug's 06:00 ON
# boots the Pi via power-apply, which is default Pi 5 behavior (no EEPROM
# changes involved).
#
# Runs as root (ExecStart of nightly-halt.service, a system unit).

hour=$(date +%H)
# Guard: only halt inside the 1a-6a window. The timer already has
# Persistent=false so a missed 01:00 is never replayed, but belt and
# suspenders — a stray manual/daytime start must be a no-op, not a halt.
[ "$hour" -ge 1 ] && [ "$hour" -lt 6 ] || exit 0

# Clear any stale alarm first — writing a new one while one is armed is EBUSY.
echo 0 > /sys/class/rtc/rtc0/wakealarm 2>/dev/null || true
# At 01:00, '06:00' resolves to today 06:00 — always in the future here.
date -d '06:00' +%s > /sys/class/rtc/rtc0/wakealarm || true

systemctl poweroff
