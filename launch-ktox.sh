#!/bin/bash
# KTOx_Pi launcher for the NeoBoX Game HAT (called from labwc autostart).
#
# Mirrors what NeoBoX's launch.sh did for the panel + audio environment, then
# starts the HDMI mirror (pygame) and the KTOX runner (sudo, for GPIO).
#
# Safety: drop ~/KTOx/NOAUTOSTART to skip on the next reboot — lets a broken
# build never lock us out of the device.
set -u

KTOX_DIR="${KTOX_DIR:-$HOME/KTOx}"
[ -f "$KTOX_DIR/NOAUTOSTART" ] && exit 0

# Brief settle for compositor + session services (pipewire) to be ready.
sleep 1

cd "$KTOX_DIR" || exit 0
export SDL_VIDEODRIVER=wayland
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
export KTOX_DIR
export KTOX_FRAME_PATH="${KTOX_FRAME_PATH:-/dev/shm/ktox_last.jpg}"
export PYTHONPATH="$KTOX_DIR:${PYTHONPATH:-}"
# Many KTOX payloads invoke tools that live in /usr/sbin (airmon-ng, airodump-ng,
# iw, john, arp-scan, dsniff). Kali's non-login PATH doesn't include sbin dirs,
# so payloads die with "command not found". Force the full root PATH here; `sudo
# -E` below preserves it into the runner's environment.
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH"

# Game HAT panel is 480x320; its HDMI board only accepts standard modes and
# scales to the panel. Feed it the smallest (640x480) for the sharpest result.
command -v wlr-randr >/dev/null && wlr-randr --output HDMI-A-1 --mode 640x480 2>/dev/null || true

# Route audio to HDMI (the HAT's speakers) at a usable level — same as NeoBoX.
hdmi_id=$(wpctl status 2>/dev/null | sed -n '/Sinks:/,/Sources:/p' | grep -i hdmi | grep -oE '[0-9]+' | head -1)
if [ -n "${hdmi_id:-}" ]; then
  wpctl set-default "$hdmi_id" 2>/dev/null || true
  wpctl set-mute "$hdmi_id" 0 2>/dev/null || true
  wpctl set-volume "$hdmi_id" 1.3 2>/dev/null || true
fi

# Pin pipewire quantum to 2048 — Pi 3B+ can't keep tiny default buffer filled
# (constant xruns -> crackly audio device-wide). Same fix as NeoBoX.
command -v pw-metadata >/dev/null && \
  pw-metadata -n settings 0 clock.force-quantum 2048 >/dev/null 2>&1 || true

mkdir -p "$KTOX_DIR/logs"
LOG_MIRROR="$KTOX_DIR/logs/hdmi_mirror.log"
LOG_RUNNER="$KTOX_DIR/logs/ktox_runner.log"

# Start the HDMI mirror (pygame on the user's Wayland seat).
python3 "$KTOX_DIR/ktox_hdmi_mirror.py" >> "$LOG_MIRROR" 2>&1 &
MIRROR_PID=$!

# Cleanup the mirror if the runner exits.
trap 'kill $MIRROR_PID 2>/dev/null' EXIT

# Run KTOX (needs root for GPIO + raw sockets; -E preserves env incl. WAYLAND_DISPLAY).
sudo -E python3 "$KTOX_DIR/ktox_bigscreen_runner.py" >> "$LOG_RUNNER" 2>&1
