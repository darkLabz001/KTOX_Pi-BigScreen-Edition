#!/usr/bin/env python3
"""HDMI compositor for KTOX_Pi on the Game HAT (480x320 panel via 640x480 HDMI).

KTOX renders its UI to a 320x320 PIL image (via ScaledDraw in the runner) and
writes it to /dev/shm/ktox_last.jpg. This compositor:

  1. Reads that frame each tick.
  2. Composes it into the centre of a 640x480 pygame surface (= 480x320 panel
     after the HAT's non-uniform downscale).
  3. Renders DESIGNED SIDEBARS in the remaining left/right space so the whole
     panel reads as one intentional UI instead of a centred square + dead bars.

The sidebars carry live status (SSID/IP/temp/uptime), a vertical KTOX brand,
and a subtle pulsing accent — cyberpunk-red to match the KTOX palette.

Coordinate conventions:
  - PANEL coords are the visible 480x320 pixels the user actually sees.
  - FB (framebuffer) coords are the 640x480 pygame surface; the HAT's HDMI
    board downscales 640x480 -> 480x320 non-uniformly (x*0.75, y*0.667). To
    place something at PANEL (px, py), draw it at FB (px*640/480, py*480/320).
"""
from __future__ import annotations

import collections
import json
import math
import os
import random
import re
import subprocess
import sys
import time

os.environ.setdefault("SDL_VIDEODRIVER", "wayland")
import pygame
from PIL import Image as _PILImage   # JPEG loader fallback (more reliable than pygame.image.load)

# ── Geometry ──────────────────────────────────────────────────────────────────
FRAME_PATH = os.environ.get("KTOX_FRAME_PATH", "/dev/shm/ktox_last.jpg")
FB_W = int(os.environ.get("KTOX_FB_W", "640"))      # pygame surface
FB_H = int(os.environ.get("KTOX_FB_H", "480"))
PANEL_W = int(os.environ.get("KTOX_PANEL_W", "480"))  # what the user sees
PANEL_H = int(os.environ.get("KTOX_PANEL_H", "320"))

CONTENT_PANEL_W = PANEL_H        # 320 — KTOX renders square
CONTENT_PANEL_H = PANEL_H        # 320
SIDE_PANEL_W = (PANEL_W - CONTENT_PANEL_W) // 2   # 80 each side


def p2fb_x(px: float) -> int:
    return int(px * FB_W / PANEL_W)


def p2fb_y(py: float) -> int:
    return int(py * FB_H / PANEL_H)


CONTENT_FB_X = p2fb_x(SIDE_PANEL_W)              # 106
CONTENT_FB_Y = 0
CONTENT_FB_W = p2fb_x(CONTENT_PANEL_W)           # 427
CONTENT_FB_H = p2fb_y(CONTENT_PANEL_H)           # 480
LEFT_FB_W = p2fb_x(SIDE_PANEL_W)                 # 106
RIGHT_FB_X = p2fb_x(SIDE_PANEL_W + CONTENT_PANEL_W)  # 533
RIGHT_FB_W = FB_W - RIGHT_FB_X                   # 107

# ── Palette ──────────────────────────────────────────────────────────────────
BG          = (5, 0, 0)
PANEL_BG    = (15, 5, 5)
ACCENT      = (139, 0, 0)
ACCENT_HOT  = (220, 35, 35)
RULE        = (60, 8, 8)
TEXT        = (210, 210, 210)
DIM         = (110, 95, 95)
WHITE       = (250, 250, 250)
GREEN       = (90, 200, 90)
AMBER       = (220, 160, 40)

POLL_INTERVAL = 0.05          # ~20 Hz frame poll
SIDEBAR_REFRESH = 0.5         # sidebar redraw cadence (sysinfo independent)

# ── Arasaka-style boot splash ────────────────────────────────────────────────
# Plays once when the mirror starts (= when labwc autostart fires after boot).
# Duration is generous (10s) because pygame's Wayland surface can take 1-3
# seconds to land above swaybg's wallpaper — the warm-up phase + long tail
# guarantee the user actually sees most of the animation.
SPLASH_DURATION = 10.0    # total seconds of intro
SPLASH_T_WARM   = 1.2     # solid red+sweep before any animation; gives pygame
                          # time to actually become visible on the panel
SPLASH_T_LOG    = 1.6     # boot-log lines start
SPLASH_T_LINE   = 0.42    # seconds per boot-log line
SPLASH_T_LOGO   = 5.0     # KTOX logo reveal
SPLASH_T_TAG    = 6.4     # tagline fade-in
SPLASH_T_FLASH  = 8.8     # final red flash → fade out

SPLASH_BOOT_LINES = [
    "> SECURE BOOT ........... VERIFIED",
    "> KERNEL MODULES ........ LOADED",
    "> WIFI ENGINE ........... ARMED",
    "> PAYLOAD VAULT ......... MOUNTED",
    "> WS BRIDGE ............. ONLINE",
    "> KTOX CORE ............. READY",
]
SPLASH_TAG = "N E T W O R K   ·   C O N T R O L   ·   S U I T E"

# Toast notification queue — auto-triggered on SSID/IP change, also
# externally appendable by writing JSON lines to /dev/shm/ktox_toasts.txt
# (each line: {"text": "..."}). Toasts fade in / hold / fade out in the
# right sidebar above the LIVE/payload footer.
TOAST_PATH = os.environ.get("KTOX_TOAST_PATH", "/dev/shm/ktox_toasts.txt")
TOAST_LIFETIME = 4.5          # total seconds visible
TOAST_FADE = 0.5              # fade in/out duration
TOAST_MAX = 3                 # max stacked at once

# Arasaka-corporate accent colours (slightly hotter than the live UI palette
# so the splash pops; matches KTOX's red-on-black brand).
SPLASH_BG    = (6, 0, 0)
SPLASH_RED   = (220, 35, 35)
SPLASH_DRED  = (130, 8, 12)
SPLASH_WHITE = (240, 240, 255)
SPLASH_CYAN  = (45, 226, 255)


# ── Live system info ─────────────────────────────────────────────────────────
class SysInfo:
    """Cached system metrics; refreshes on a 5-second cadence (subprocess
    spawns are expensive on a Pi 3B+ so we don't poll every frame)."""

    __slots__ = ("ip", "ssid", "temp_c", "uptime_min", "rx_kbps",
                 "wifi_dbm", "throttled", "rx_history",
                 "cpu_load", "n_cores", "active_payload",
                 "_rx_bytes", "_rx_t", "_last_refresh",
                 "_prev_ssid", "_prev_ip", "_prev_payload")

    # Bit meanings of vcgencmd get_throttled (Raspberry Pi); we flag any of
    # the live-now bits, not the "occurred since boot" bits.
    THROTTLED_UV_NOW    = 0x1     # under-voltage RIGHT NOW
    THROTTLED_FREQ_NOW  = 0x2     # ARM frequency capped right now
    THROTTLED_THROT_NOW = 0x4     # currently throttled
    THROTTLED_TEMP_NOW  = 0x8     # soft temperature limit active

    RX_HISTORY_LEN = 60   # 60 samples × 5s refresh = 5-minute window

    def __init__(self):
        self.ip = "—"
        self.ssid = "—"
        self.temp_c = 0
        self.uptime_min = 0
        self.rx_kbps = 0.0
        self.wifi_dbm = 0          # 0 = no signal; otherwise negative dBm
        self.throttled = 0         # raw vcgencmd get_throttled int
        self.rx_history = collections.deque(maxlen=self.RX_HISTORY_LEN)
        self.cpu_load = 0.0        # 1-min loadavg / n_cores → 0.0..1.0+
        try:
            self.n_cores = os.cpu_count() or 4
        except Exception:
            self.n_cores = 4
        self.active_payload = None # name of currently-running payload or None
        self._rx_bytes = 0
        self._rx_t = time.time()
        self._last_refresh = 0.0
        # Previous values for change detection (auto-toasts)
        self._prev_ssid = None
        self._prev_ip = None
        self._prev_payload = None

    def changes(self):
        """Yield (kind, text) tuples for state changes since last call.
        First call after init seeds previous values silently."""
        out = []
        if self._prev_ssid is None:
            self._prev_ssid = self.ssid
        elif self.ssid != self._prev_ssid:
            if self.ssid == "—":
                out.append(("wifi", "WiFi disconnected"))
            else:
                out.append(("wifi", f"Joined  {self.ssid[:12]}"))
            self._prev_ssid = self.ssid

        if self._prev_ip is None:
            self._prev_ip = self.ip
        elif self.ip != self._prev_ip:
            if self.ip != "—":
                out.append(("ip", f"IP  {self.ip}"))
            self._prev_ip = self.ip

        if self._prev_payload != self.active_payload:
            if self.active_payload:
                out.append(("payload", f"Run  {self.active_payload[:12]}"))
            elif self._prev_payload:
                out.append(("payload", f"End  {self._prev_payload[:12]}"))
            self._prev_payload = self.active_payload
        return out

    def refresh(self, now: float, force: bool = False):
        if not force and (now - self._last_refresh) < 5.0:
            return
        self._last_refresh = now

        # IP (prefer wlan0, fall back to anything globally scoped)
        try:
            r = subprocess.run(["ip", "-4", "-o", "addr", "show"],
                               capture_output=True, text=True, timeout=2).stdout
            best = "—"
            for line in r.splitlines():
                m = re.search(r"\d+:\s+(\S+)\s+inet\s+(\d+\.\d+\.\d+\.\d+)/", line)
                if not m:
                    continue
                iface, ip = m.group(1), m.group(2)
                if iface == "lo":
                    continue
                if iface.startswith("wlan"):
                    best = ip
                    break
                if best == "—":
                    best = ip
            self.ip = best
        except Exception:
            pass

        # SSID — try nmcli first (it's already used by KTOX so it's installed)
        try:
            r = subprocess.run(
                ["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"],
                capture_output=True, text=True, timeout=2,
            ).stdout
            for line in r.splitlines():
                if line.startswith("yes:"):
                    self.ssid = line.split(":", 1)[1] or "—"
                    break
            else:
                self.ssid = "—"
        except Exception:
            pass

        # Temperature
        try:
            with open("/sys/class/thermal/thermal_zone0/temp") as f:
                self.temp_c = int(f.read().strip()) // 1000
        except Exception:
            pass

        # Uptime
        try:
            with open("/proc/uptime") as f:
                self.uptime_min = int(float(f.read().split()[0]) // 60)
        except Exception:
            pass

        # WiFi throughput estimate (across wlan0/wlan1)
        try:
            total = 0
            for iface in ("wlan0", "wlan1"):
                p = f"/sys/class/net/{iface}/statistics/rx_bytes"
                if os.path.exists(p):
                    with open(p) as f:
                        total += int(f.read().strip())
            dt = max(0.1, now - self._rx_t)
            if self._rx_bytes:
                self.rx_kbps = max(0.0, (total - self._rx_bytes) / dt / 1024.0)
            self._rx_bytes = total
            self._rx_t = now
            self.rx_history.append(self.rx_kbps)
        except Exception:
            pass

        # WiFi signal level (dBm). /proc/net/wireless gives it without sudo.
        # Columns: iface | status | link_q | level | noise | ...
        try:
            self.wifi_dbm = 0
            with open("/proc/net/wireless") as f:
                for line in f.read().splitlines()[2:]:
                    parts = line.split()
                    if not parts or not parts[0].startswith("wlan"):
                        continue
                    # Level field can have a trailing dot; strip it.
                    lvl = parts[3].rstrip(".")
                    self.wifi_dbm = int(float(lvl))
                    break
        except Exception:
            pass

        # Throttling status — Pi 3B+ under-voltage detection.
        # vcgencmd is in /usr/bin, present on Pi OS.
        try:
            r = subprocess.run(["vcgencmd", "get_throttled"],
                               capture_output=True, text=True, timeout=2).stdout
            m = re.search(r"0x([0-9a-fA-F]+)", r)
            self.throttled = int(m.group(1), 16) if m else 0
        except Exception:
            pass

        # CPU load (1-min avg, normalised to core count)
        try:
            with open("/proc/loadavg") as f:
                load_1m = float(f.read().split()[0])
            self.cpu_load = load_1m / max(1, self.n_cores)
        except Exception:
            pass

        # Active payload — KTOX writes /dev/shm/ktox_payload_state.json with
        # {"running": bool, "name": "category/script", ...}
        try:
            with open("/dev/shm/ktox_payload_state.json") as f:
                state = json.load(f)
            if state.get("running"):
                name = state.get("name") or state.get("payload") or ""
                # Strip "category/" prefix so the sidebar shows just the script
                name = name.split("/")[-1].replace(".py", "")
                self.active_payload = name or None
            else:
                self.active_payload = None
        except Exception:
            self.active_payload = None

    def uptime_str(self) -> str:
        h, m = divmod(self.uptime_min, 60)
        return f"{h:d}h{m:02d}" if h else f"{m:d}m"


# ── Drawing ──────────────────────────────────────────────────────────────────
class ToastQueue:
    """Bottom-of-sidebar transient messages. Each toast lives TOAST_LIFETIME
    seconds with TOAST_FADE in/out. Up to TOAST_MAX visible — older ones
    drop off the top of the stack."""

    def __init__(self):
        self._items = collections.deque()    # list of (text, t0)
        self._toast_file_mtime = 0.0

    def push(self, text: str):
        text = text.strip()[:18]
        if not text:
            return
        if len(self._items) >= TOAST_MAX:
            self._items.popleft()
        self._items.append((text, time.time()))

    def poll_file(self):
        """Pick up externally-queued toasts from TOAST_PATH (newline-delimited
        JSON: {"text":"..."}). Empties the file after reading so toasts
        only fire once. Best-effort — silent on errors."""
        try:
            mt = os.path.getmtime(TOAST_PATH)
        except OSError:
            return
        if mt == self._toast_file_mtime:
            return
        self._toast_file_mtime = mt
        try:
            with open(TOAST_PATH) as f:
                lines = f.readlines()
            open(TOAST_PATH, "w").close()
            for ln in lines:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    obj = json.loads(ln)
                    txt = obj.get("text") or obj.get("msg") or ""
                except Exception:
                    txt = ln
                self.push(txt)
        except Exception:
            pass

    def active(self, now: float):
        """Yield (text, alpha 0..1) for toasts currently visible. Drops
        expired ones in place."""
        out = []
        while self._items and (now - self._items[0][1]) > TOAST_LIFETIME:
            self._items.popleft()
        for text, t0 in self._items:
            age = now - t0
            if age < TOAST_FADE:
                alpha = age / TOAST_FADE
            elif age > TOAST_LIFETIME - TOAST_FADE:
                alpha = max(0.0, (TOAST_LIFETIME - age) / TOAST_FADE)
            else:
                alpha = 1.0
            out.append((text, alpha))
        return out


def _font(size_px: int, bold: bool = False) -> pygame.font.Font:
    # SysFont with explicit path falls back gracefully if dejavu isn't found.
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            return pygame.font.Font(p, size_px)
    return pygame.font.SysFont("monospace", size_px, bold=bold)


def _vline(surf, x, y0, y1, color, w=1):
    pygame.draw.line(surf, color, (x, y0), (x, y1), w)


def _hline(surf, y, x0, x1, color, w=1):
    pygame.draw.line(surf, color, (x0, y), (x1, y), w)


def _draw_signal_bars(surf, x, y, dbm: int, on_col, off_col, bar_w=None, gap=None, h_step=None):
    """5-bar phone-style signal strength indicator.
    dBm scale: -30 great, -50 good, -70 OK, -90 poor. 0 = no signal."""
    bar_w  = bar_w  or max(1, p2fb_x(3))
    gap    = gap    or max(1, p2fb_x(1))
    h_step = h_step or max(1, p2fb_y(2))
    if dbm == 0:
        bars_lit = 0
    else:
        # Map -85..-35 → 0..5 bars
        bars_lit = max(0, min(5, int((dbm + 85) / 10)))
    max_h = h_step * 5
    for i in range(5):
        bar_h = h_step * (i + 1)
        bx = x + i * (bar_w + gap)
        by = y + max_h - bar_h
        col = on_col if i < bars_lit else off_col
        pygame.draw.rect(surf, col, (bx, by, bar_w, bar_h))


def _draw_sparkline(surf, x, y, w, h, values, color, baseline_col=None, max_val=None):
    """Draw a tiny line graph of `values` (oldest left, newest right) inside
    the box (x, y, w, h). max_val auto-scales if not given."""
    if baseline_col:
        pygame.draw.rect(surf, baseline_col, (x, y, w, h), 1)
    if not values or len(values) < 2:
        return
    if max_val is None:
        max_val = max(max(values), 1.0)
    pts = []
    n = len(values)
    for i, v in enumerate(values):
        px = x + int(i * (w - 1) / (n - 1))
        py = y + h - 1 - int(min(v, max_val) / max_val * (h - 2))
        pts.append((px, py))
    pygame.draw.lines(surf, color, False, pts, 1)


def _draw_load_bar(surf, x, y, w, h, ratio: float, fill_col, frame_col):
    """Tiny horizontal load meter. ratio: 0.0..1.0+ (clamp)."""
    pygame.draw.rect(surf, frame_col, (x, y, w, h), 1)
    r = max(0.0, min(1.0, ratio))
    fill_w = int((w - 2) * r)
    if fill_w > 0:
        pygame.draw.rect(surf, fill_col, (x + 1, y + 1, fill_w, h - 2))


def draw_left_sidebar(surf, fonts, t):
    """Vertical KTOX brand + animated pulse + chevron motif."""
    x0, x1 = 0, LEFT_FB_W
    y0, y1 = 0, FB_H
    pygame.draw.rect(surf, PANEL_BG, (x0, y0, LEFT_FB_W, FB_H))

    # Soft gradient edge to the content area on the right
    for i in range(p2fb_x(6)):
        col = (
            PANEL_BG[0] + (BG[0] - PANEL_BG[0]) * i // max(1, p2fb_x(6)),
            PANEL_BG[1],
            PANEL_BG[2],
        )
        _vline(surf, x1 - 1 - i, y0, y1, col)

    # KTOX brand — stacked, big, bold
    brand_font = fonts["brand"]
    letters = list("KTOX")
    n = len(letters)
    spacing = FB_H // (n + 1)
    for i, ch in enumerate(letters):
        # Pulse the centre letter index, very subtly
        pulse = (math.sin(t * 1.6 + i * 0.4) * 0.5 + 0.5)
        col = (
            int(ACCENT[0] + (ACCENT_HOT[0] - ACCENT[0]) * pulse * 0.45),
            int(ACCENT[1] + (ACCENT_HOT[1] - ACCENT[1]) * pulse * 0.45),
            int(ACCENT[2] + (ACCENT_HOT[2] - ACCENT[2]) * pulse * 0.45),
        )
        s = brand_font.render(ch, True, col)
        sx = (LEFT_FB_W - s.get_width()) // 2
        sy = spacing * (i + 1) - s.get_height() // 2
        surf.blit(s, (sx, sy))

    # Vertical accent bar (a scrolling rectangle of phosphor)
    bar_x = p2fb_x(SIDE_PANEL_W - 8)
    pygame.draw.line(surf, ACCENT, (bar_x, y0), (bar_x, y1), 1)
    span_h = FB_H // 4
    phase = (t * 0.35) % 1.0
    py = int(phase * (FB_H + span_h) - span_h)
    grad_h = max(1, span_h)
    for i in range(grad_h):
        alpha = 1.0 - abs((i / grad_h) - 0.5) * 2
        col = (
            int(ACCENT[0] + (ACCENT_HOT[0] - ACCENT[0]) * alpha),
            int(ACCENT[1] + (ACCENT_HOT[1] - ACCENT[1]) * alpha),
            int(ACCENT[2] + (ACCENT_HOT[2] - ACCENT[2]) * alpha),
        )
        y = py + i
        if 0 <= y < FB_H:
            pygame.draw.line(surf, col, (bar_x - 1, y), (bar_x + 1, y), 1)

    # Top + bottom corner chevrons
    chev = p2fb_y(6)
    for cy in (chev, FB_H - chev - p2fb_y(8)):
        pygame.draw.line(surf, ACCENT, (p2fb_x(6), cy), (p2fb_x(14), cy + chev // 2), 1)
        pygame.draw.line(surf, ACCENT, (p2fb_x(6), cy + chev), (p2fb_x(14), cy + chev // 2), 1)


def draw_toasts(surf, fonts, toasts, x0, top_y, width, t):
    """Stack of fading toast notifications in the lower right sidebar."""
    if not toasts:
        return
    micro = fonts["micro"]
    label = fonts["label"]
    row_h = p2fb_y(13)
    y = top_y
    for text, alpha in toasts:
        # Background pill with alpha
        bg_alpha = int(180 * alpha)
        pill = pygame.Surface((width, row_h - 2), pygame.SRCALPHA)
        pill.fill((30, 5, 5, bg_alpha))
        pygame.draw.rect(pill, (180, 30, 30, int(220 * alpha)),
                         (0, 0, width, row_h - 2), 1)
        surf.blit(pill, (x0, y))
        # Text
        col_a = int(240 * alpha)
        if col_a > 4:
            ts = label.render(text, True, (240, 240, 240))
            ts.set_alpha(col_a)
            surf.blit(ts, (x0 + p2fb_x(3), y + p2fb_y(2)))
        y += row_h


def draw_right_sidebar(surf, fonts, info: SysInfo, t, toasts):
    """Status panel: clock, WiFi signal+SSID, IP, temp/up, RX sparkline,
    throttling warning (only if active), live activity dot."""
    x0 = RIGHT_FB_X
    pygame.draw.rect(surf, PANEL_BG, (x0, 0, RIGHT_FB_W, FB_H))

    # Soft gradient on the inside edge
    for i in range(p2fb_x(6)):
        col = (
            PANEL_BG[0] + (BG[0] - PANEL_BG[0]) * i // max(1, p2fb_x(6)),
            PANEL_BG[1],
            PANEL_BG[2],
        )
        _vline(surf, x0 + i, 0, FB_H, col)

    label_font = fonts["label"]
    value_font = fonts["value"]
    big_font   = fonts["big"]
    micro_font = fonts["micro"]

    pad_x = p2fb_x(8)
    inner_w = RIGHT_FB_W - pad_x * 2

    # Top header — "STATUS" with rule line
    hdr = label_font.render("STATUS", True, ACCENT)
    surf.blit(hdr, (x0 + (RIGHT_FB_W - hdr.get_width()) // 2, p2fb_y(6)))
    _hline(surf, p2fb_y(19),
           x0 + p2fb_x(6), x0 + RIGHT_FB_W - p2fb_x(6), ACCENT)

    # Big "live" clock (HH:MM)
    clk = time.strftime("%H:%M")
    clk_s = big_font.render(clk, True, WHITE)
    surf.blit(clk_s, (x0 + (RIGHT_FB_W - clk_s.get_width()) // 2, p2fb_y(24)))
    secs = time.strftime("%S")
    secs_s = micro_font.render(secs, True, DIM)
    surf.blit(secs_s, (x0 + (RIGHT_FB_W - secs_s.get_width()) // 2, p2fb_y(50)))

    # ── WiFi: signal bars + SSID ───────────────────────────────────────────
    y = p2fb_y(64)
    lbl = label_font.render("WIFI", True, DIM)
    surf.blit(lbl, (x0 + pad_x, y))
    # Signal bars to the right of the label
    bars_x = x0 + RIGHT_FB_W - pad_x - p2fb_x(20)
    _draw_signal_bars(surf, bars_x, y, info.wifi_dbm,
                      on_col=GREEN if info.wifi_dbm > -75 else AMBER,
                      off_col=RULE)
    # SSID on its own line below
    ssid_txt = info.ssid[:11] if info.ssid != "—" else "no link"
    ssid_col = GREEN if info.wifi_dbm < 0 else DIM
    ssid_s = value_font.render(ssid_txt, True, ssid_col)
    surf.blit(ssid_s, (x0 + pad_x, y + p2fb_y(11)))

    # ── IP ─────────────────────────────────────────────────────────────────
    y = p2fb_y(92)
    surf.blit(label_font.render("IP", True, DIM), (x0 + pad_x, y))
    ip_col = GREEN if info.ip != "—" else DIM
    surf.blit(value_font.render(info.ip[:15], True, ip_col),
              (x0 + pad_x, y + p2fb_y(11)))

    # ── TEMP / UP on one row ───────────────────────────────────────────────
    y = p2fb_y(120)
    surf.blit(label_font.render("TEMP", True, DIM), (x0 + pad_x, y))
    surf.blit(label_font.render("UP", True, DIM),
              (x0 + pad_x + p2fb_x(36), y))
    temp_col = AMBER if info.temp_c >= 65 else TEXT
    surf.blit(value_font.render(f"{info.temp_c}C", True, temp_col),
              (x0 + pad_x, y + p2fb_y(11)))
    surf.blit(value_font.render(info.uptime_str(), True, TEXT),
              (x0 + pad_x + p2fb_x(36), y + p2fb_y(11)))

    # ── RX sparkline ───────────────────────────────────────────────────────
    y = p2fb_y(150)
    spark_h = p2fb_y(18)
    surf.blit(label_font.render("RX", True, DIM), (x0 + pad_x, y))
    rx_now = info.rx_kbps
    rx_str = (f"{int(rx_now)}k" if rx_now < 1000
              else f"{rx_now / 1024:.1f}M")
    rx_s = micro_font.render(rx_str, True, TEXT)
    surf.blit(rx_s, (x0 + RIGHT_FB_W - pad_x - rx_s.get_width(), y))
    _draw_sparkline(
        surf, x0 + pad_x, y + p2fb_y(10), inner_w, spark_h,
        list(info.rx_history), ACCENT_HOT, baseline_col=RULE,
    )

    # ── CPU load mini-bar ─────────────────────────────────────────────────
    y = p2fb_y(178)
    surf.blit(label_font.render("CPU", True, DIM), (x0 + pad_x, y))
    cpu_pct = int(info.cpu_load * 100)
    cpu_str = f"{min(999, cpu_pct)}%"
    cpu_col = AMBER if info.cpu_load > 0.75 else TEXT
    cpu_s = micro_font.render(cpu_str, True, cpu_col)
    surf.blit(cpu_s, (x0 + RIGHT_FB_W - pad_x - cpu_s.get_width(), y))
    _draw_load_bar(
        surf, x0 + pad_x, y + p2fb_y(10), inner_w, p2fb_y(5),
        info.cpu_load,
        fill_col=AMBER if info.cpu_load > 0.75 else ACCENT_HOT,
        frame_col=RULE,
    )

    # ── Throttling warning (only when actively under-voltage / capped) ─────
    # Bits 0,1,2,3 are the live-now flags; bits 16+ are sticky "ever seen".
    live_throttle = info.throttled & 0xF
    if live_throttle:
        y = p2fb_y(198)
        # Pulsing red warning bar
        warn_pulse = 0.5 + 0.5 * math.sin(t * 4.0)
        warn_col = (
            int(ACCENT[0] + (ACCENT_HOT[0] - ACCENT[0]) * warn_pulse),
            int(ACCENT[1] + (ACCENT_HOT[1] - ACCENT[1]) * warn_pulse),
            int(ACCENT[2] + (ACCENT_HOT[2] - ACCENT[2]) * warn_pulse),
        )
        pygame.draw.rect(surf, warn_col,
                         (x0 + pad_x, y, inner_w, p2fb_y(14)))
        msgs = []
        if live_throttle & SysInfo.THROTTLED_UV_NOW:    msgs.append("UV")
        if live_throttle & SysInfo.THROTTLED_THROT_NOW: msgs.append("THR")
        if live_throttle & SysInfo.THROTTLED_FREQ_NOW:  msgs.append("CAP")
        if live_throttle & SysInfo.THROTTLED_TEMP_NOW:  msgs.append("HOT")
        warn_txt = "PWR " + "/".join(msgs)
        warn_s = label_font.render(warn_txt, True, WHITE)
        surf.blit(warn_s,
                  (x0 + (RIGHT_FB_W - warn_s.get_width()) // 2,
                   y + p2fb_y(2)))

    # ── Toast notifications (above the footer) ─────────────────────────────
    # Reserve up to TOAST_MAX rows just above the footer.
    if toasts:
        toast_top = FB_H - p2fb_y(22) - p2fb_y(13) * len(toasts)
        draw_toasts(surf, fonts, toasts,
                    x0 + p2fb_x(3), toast_top,
                    RIGHT_FB_W - p2fb_x(6), t)

    # ── Bottom footer ──────────────────────────────────────────────────────
    # If a payload is running, surface its name in the footer (more useful
    # than a generic LIVE label); otherwise keep the pulsing LIVE dot.
    dot_pulse = (math.sin(t * 3.0) * 0.5 + 0.5)
    dot_col = (
        int(ACCENT[0] + (ACCENT_HOT[0] - ACCENT[0]) * dot_pulse),
        int(ACCENT[1] + (ACCENT_HOT[1] - ACCENT[1]) * dot_pulse),
        int(ACCENT[2] + (ACCENT_HOT[2] - ACCENT[2]) * dot_pulse),
    )
    if info.active_payload:
        # Active payload: full-width pulsing bar with the name
        bar_y = FB_H - p2fb_y(18)
        pygame.draw.rect(surf, dot_col,
                         (x0 + p2fb_x(4), bar_y,
                          RIGHT_FB_W - p2fb_x(8), p2fb_y(14)))
        name = info.active_payload
        name_s = label_font.render(name[:13], True, BG)
        surf.blit(name_s, (x0 + (RIGHT_FB_W - name_s.get_width()) // 2,
                           bar_y + p2fb_y(2)))
    else:
        pygame.draw.circle(surf, dot_col,
                           (x0 + RIGHT_FB_W // 2, FB_H - p2fb_y(14)),
                           p2fb_y(3))
        foot = micro_font.render("LIVE", True, DIM)
        surf.blit(foot, (x0 + (RIGHT_FB_W - foot.get_width()) // 2,
                         FB_H - p2fb_y(10)))


# ── Boot splash drawing ──────────────────────────────────────────────────────
# ── Boot splash audio ───────────────────────────────────────────────────────
def _splash_bleep(freq_hz=820, ms=160, vol=0.35):
    """Synthesise a short square-wave bleep and play it once. Lazy-imports
    numpy + lazy-inits mixer so the mirror works even if audio isn't ready."""
    try:
        import numpy as _np
        if not pygame.mixer.get_init():
            pygame.mixer.init(frequency=22050, size=-16, channels=1)
        n = int(22050 * ms / 1000.0)
        t = _np.arange(n) / 22050.0
        # Square wave + brief envelope to avoid clicks
        wave = _np.where(_np.sin(2 * _np.pi * freq_hz * t) >= 0, 1.0, -1.0)
        env = _np.minimum(_np.ones(n),
                          _np.minimum(t * 50, (ms / 1000.0 - t) * 50))
        env = _np.clip(env, 0.0, 1.0)
        samples = (wave * env * vol * 32767).astype(_np.int16)
        snd = pygame.mixer.Sound(buffer=samples.tobytes())
        snd.play()
    except Exception as e:
        print(f"[splash] bleep failed: {e}", file=sys.stderr)


def _splash_scan_beam(surf, t):
    """Vertical red beam that scans across the screen during logo reveal."""
    # Beam exists from logo reveal through start of flash.
    if t < SPLASH_T_LOGO or t >= SPLASH_T_FLASH:
        return
    phase = (t - SPLASH_T_LOGO) / max(0.1, SPLASH_T_FLASH - SPLASH_T_LOGO)
    # Sweep left → right → left, oscillating
    x = int((math.sin(phase * math.pi * 1.5) * 0.5 + 0.5) * (FB_W - 2)) + 1
    # Semi-transparent beam with bright core
    beam = pygame.Surface((6, FB_H), pygame.SRCALPHA)
    pygame.draw.rect(beam, (220, 35, 35, 60), (0, 0, 6, FB_H))
    pygame.draw.line(beam, (255, 80, 80, 200), (3, 0), (3, FB_H), 1)
    surf.blit(beam, (x - 3, 0))


def _splash_glitch(surf, intensity: float):
    """Lightweight glitch: just paint random horizontal red bars across the
    screen. Skipping the subsurface-copy trick because it's expensive on the
    Pi 3B+ at 640x480 and stalls pygame's flip cadence."""
    bars = int(intensity * 3) + 1
    for _ in range(bars):
        y = random.randint(0, FB_H - 4)
        col = SPLASH_DRED if random.random() < 0.7 else SPLASH_RED
        pygame.draw.rect(surf, col, (0, y, FB_W, random.randint(1, 3)))


def _splash_chroma_text(surf, font, text, center, jitter=True):
    """Render text with red/cyan/white chromatic aberration offset — the
    Arasaka glitch-logo look."""
    r = font.render(text, True, (255, 60, 60))
    c = font.render(text, True, SPLASH_CYAN)
    w = font.render(text, True, SPLASH_WHITE)
    rect = w.get_rect(center=center)
    j = random.randint(-2, 2) if jitter else 0
    surf.blit(r, rect.move(-3 + j, 0))
    surf.blit(c, rect.move(3 - j, 0))
    surf.blit(w, rect)


def _splash_corners(surf, color=SPLASH_DRED, L=None):
    """Corporate HUD frame brackets in the four corners."""
    if L is None:
        L = p2fb_x(14)
    inset = p2fb_x(6)
    for (x, y, dx, dy) in [
        (inset, inset, 1, 1),
        (FB_W - inset, inset, -1, 1),
        (inset, FB_H - inset, 1, -1),
        (FB_W - inset, FB_H - inset, -1, -1),
    ]:
        pygame.draw.line(surf, color, (x, y), (x + dx * L, y), 2)
        pygame.draw.line(surf, color, (x, y), (x, y + dy * L), 2)


def draw_boot_splash(surf, t, fonts):
    surf.fill(SPLASH_BG)

    # 1) Opening red sweep down the screen (0 → SPLASH_T_WARM).
    if t < SPLASH_T_WARM:
        sweep_y = int((t / SPLASH_T_WARM) * FB_H)
        pygame.draw.rect(surf, SPLASH_DRED, (0, 0, FB_W, sweep_y))
        pygame.draw.line(surf, SPLASH_RED, (0, sweep_y), (FB_W, sweep_y), 2)
    else:
        # After sweep completes, hold the dark-red ground until other phases
        # paint over it. This guarantees there's never a flash of pure BG.
        pygame.draw.rect(surf, SPLASH_DRED, (0, 0, FB_W, FB_H))
        pygame.draw.rect(surf, SPLASH_BG,
                         (p2fb_x(8), p2fb_y(8), FB_W - p2fb_x(16), FB_H - p2fb_y(16)))

    # 2) Corner HUD brackets from 0.5s onward.
    if t >= 0.5:
        _splash_corners(surf)

    # 3) Terminal boot log, line-by-line, fades as the logo reveals.
    if SPLASH_T_LOG <= t < SPLASH_T_LOGO + 0.9:
        log = pygame.Surface((FB_W, FB_H), pygame.SRCALPHA)
        shown = int((t - SPLASH_T_LOG) / SPLASH_T_LINE)
        line_y = p2fb_y(40)
        line_dy = p2fb_y(20)
        for i, line in enumerate(SPLASH_BOOT_LINES[:shown + 1]):
            color = SPLASH_WHITE if i < shown else SPLASH_RED
            # Cursor flicker on the actively-typing line
            txt = line
            if i == shown and int(t * 2) % 2 == 0:
                txt = line + " _"
            log.blit(fonts["splash_mono"].render(txt, True, color),
                     (p2fb_x(26), line_y + line_dy * i))
        if t > SPLASH_T_LOGO:
            alpha = int(255 * max(0.0, 1 - (t - SPLASH_T_LOGO) / 0.9))
            log.set_alpha(alpha)
        surf.blit(log, (0, 0))

    # 4) KTOX logo reveal with chromatic aberration + growing underline.
    if t >= SPLASH_T_LOGO:
        _splash_chroma_text(
            surf, fonts["splash_logo"], "KTOX",
            (FB_W // 2, FB_H // 2 - p2fb_y(6)),
        )
        p = min(1.0, (t - SPLASH_T_LOGO) / 1.4)
        bar_w = int(p2fb_x(220) * p)
        pygame.draw.rect(
            surf, SPLASH_RED,
            (FB_W // 2 - bar_w // 2, FB_H // 2 + p2fb_y(30), bar_w, 4),
        )

    # 5) Tagline fade-in.
    if t >= SPLASH_T_TAG:
        a = min(1.0, (t - SPLASH_T_TAG) / 0.8)
        col = tuple(int(c * a) for c in SPLASH_WHITE)
        tag = fonts["splash_tag"].render(SPLASH_TAG, True, col)
        surf.blit(tag, tag.get_rect(center=(FB_W // 2,
                                            FB_H // 2 + p2fb_y(56))))

    # 6) Glitch intensity spikes on logo reveal + final flash.
    gi = 0.0
    if SPLASH_T_LOGO - 0.3 <= t < SPLASH_T_LOGO + 0.7:
        gi = 0.9
    elif SPLASH_T_LOG <= t < SPLASH_T_LOGO:
        gi = 0.15
    elif t >= SPLASH_T_FLASH:
        gi = 1.0
    if gi:
        _splash_glitch(surf, gi)

    # 6b) Vertical scanning beam during the logo reveal → flash window.
    _splash_scan_beam(surf, t)

    # 7) End red flash transition to live UI.
    if t >= SPLASH_T_FLASH:
        a = int(255 * min(1.0, (t - SPLASH_T_FLASH) /
                          (SPLASH_DURATION - SPLASH_T_FLASH)))
        flash = pygame.Surface((FB_W, FB_H))
        flash.fill(SPLASH_RED)
        flash.set_alpha(a)
        surf.blit(flash, (0, 0))


def draw_content_frame(surf, scaled_frame):
    """KTOX render area — blit pre-scaled frame + a 1px accent frame."""
    if scaled_frame is not None:
        surf.blit(scaled_frame, (CONTENT_FB_X, CONTENT_FB_Y))
    # Thin accent border
    pygame.draw.rect(surf, ACCENT,
                     (CONTENT_FB_X - 1, CONTENT_FB_Y,
                      CONTENT_FB_W + 2, CONTENT_FB_H),
                     1)


# ── Main loop ────────────────────────────────────────────────────────────────
def main() -> int:
    pygame.display.init()
    pygame.font.init()
    # DOUBLEBUF: pygame flips an off-screen buffer atomically so the user
    # never sees a mid-draw frame (otherwise a slow redraw on the Pi 3B+ can
    # leak partial state -> the "white blink" symptom).
    flags = pygame.FULLSCREEN | pygame.NOFRAME | pygame.DOUBLEBUF
    screen = pygame.display.set_mode((FB_W, FB_H), flags)
    pygame.mouse.set_visible(False)
    pygame.display.set_caption("KTOX")

    fonts = {
        "brand":  _font(p2fb_y(28), bold=True),
        "label":  _font(p2fb_y(8),  bold=True),
        # IP is 15 chars max (xxx.xxx.xxx.xxx); shrink the value font enough
        # to fit it. 9px ≈ 18 columns at the current width.
        "value":  _font(p2fb_y(9),  bold=True),
        "big":    _font(p2fb_y(20), bold=True),
        "micro":  _font(p2fb_y(7)),
        # Boot splash fonts (sized for the full FB, not the sidebar).
        "splash_mono": _font(p2fb_y(11)),
        "splash_logo": _font(p2fb_y(56), bold=True),
        "splash_tag":  _font(p2fb_y(11)),
    }

    info = SysInfo()
    info.refresh(time.time(), force=True)
    toasts = ToastQueue()

    last_frame_mtime = 0.0
    cached_frame = None              # raw PIL/pygame image, as loaded
    cached_scaled = None             # smoothscaled to CONTENT_FB_W x H
    last_sidebar_t = 0.0
    silent_load_errors = 0           # only log if errors persist

    # Boot splash phase — runs first, then the compositor takes over.
    splash_t0 = time.time()
    splash_bleeped = False

    while True:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return 0

        now = time.time()

        # ── Arasaka boot splash (first SPLASH_DURATION seconds) ─────────────
        splash_elapsed = now - splash_t0
        if splash_elapsed < SPLASH_DURATION:
            # One-shot bleep at the logo reveal.
            if not splash_bleeped and splash_elapsed >= SPLASH_T_LOGO:
                _splash_bleep()
                splash_bleeped = True
            draw_boot_splash(screen, splash_elapsed, fonts)
            pygame.display.flip()
            # Splash needs ~30 FPS for smooth glitch animation.
            time.sleep(0.033)
            continue

        info.refresh(now)
        # Auto-toast any state changes detected this refresh.
        for kind, text in info.changes():
            toasts.push(text)
        toasts.poll_file()

        # Reload KTOX content frame if it changed
        try:
            mt = os.path.getmtime(FRAME_PATH)
        except OSError:
            mt = 0.0
        frame_dirty = (mt > 0 and mt != last_frame_mtime)
        if frame_dirty:
            try:
                # Load via PIL → convert to pygame Surface. pygame.image.load
                # silently lacks JPEG support in some headless setups (its
                # libjpeg dep is optional via SDL_image); PIL bundles its own
                # libjpeg so this path is reliable.
                pil_img = _PILImage.open(FRAME_PATH).convert("RGB")
                cached_frame = pygame.image.frombytes(
                    pil_img.tobytes(), pil_img.size, "RGB")
                cached_scaled = pygame.transform.smoothscale(
                    cached_frame, (CONTENT_FB_W, CONTENT_FB_H))
                last_frame_mtime = mt
                silent_load_errors = 0
            except Exception as e:
                silent_load_errors += 1
                if silent_load_errors in (10, 100, 1000):
                    print(f"[mirror] {silent_load_errors} consecutive frame "
                          f"load failures: {e}", file=sys.stderr)

        # Redraw on content change OR sidebar-animation cadence.
        if frame_dirty or (now - last_sidebar_t) >= SIDEBAR_REFRESH:
            last_sidebar_t = now
            screen.fill(BG)
            draw_left_sidebar(screen, fonts, now)
            draw_content_frame(screen, cached_scaled)
            draw_right_sidebar(screen, fonts, info, now, toasts.active(now))
            pygame.display.flip()

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    sys.exit(main())
