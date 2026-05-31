#!/usr/bin/env python3
"""KTOX_Pi bootstrap for the NeoBoX Game HAT (480x320 HDMI + 12 GPIO buttons).

KTOX_Pi was written for the Waveshare 1.44" SPI LCD HAT (128x128) on a Pi Zero
2W. Three transparent monkey-patches let us run it on our Pi 3B+/Game HAT with
ZERO upstream source changes:

  1. **Fake LCD**: ``LCD_1in44`` is replaced in ``sys.modules`` with a fake
     whose ``LCD_ShowImage`` writes the rendered PIL frame to
     ``/dev/shm/ktox_last.jpg``. ``ktox_hdmi_mirror.py`` reads that file and
     blits it to the HDMI panel via pygame. (``LCD_Config.Driver_Delay_ms`` is
     similarly stubbed.)

  2. **2.5x scaling**: ``ImageDraw.Draw`` is wrapped so every coord passed in
     gets scaled by 2.5 (128-base → 320-base), every ``width=`` argument
     scales similarly, and ``textbbox`` returns *1x-equivalent* measurements
     so KTOX's centering arithmetic ``(128-w)//2`` still produces the right
     positions. ``ImageFont.truetype`` is wrapped so every font requested at
     size ``N`` loads at size ``int(N*2.5)``. Net effect: KTOX renders natively
     at 320x320 with 2.5x-bigger fonts → sharp text instead of upscaled blur.

  3. **PINS override**: ``ktox_device.PINS`` is replaced with the Game HAT's
     12-button pin map, mapping d-pad+ABXY+START+SELECT to KTOX's 5-way
     joystick + KEY1/KEY2/KEY3 semantics.

Game HAT physical buttons:
    UP=5  DOWN=6  LEFT=13  RIGHT=19  A=26  B=12  X=16  Y=20  START=21
    SELECT=4  L=23  R=18

KTOX logical names mapped here:
    d-pad   → joystick UP/DOWN/LEFT/RIGHT
    A       → KEY_PRESS_PIN  (OK/select)
    B       → KEY1_PIN       (back)
    START   → KEY2_PIN       (home)
    SELECT  → KEY3_PIN       (stop/exit attack)

X, Y, L, R stay unmapped (free for future chord shortcuts).
"""
from __future__ import annotations

import os
import sys
import time
import types

import PIL.Image as _PILImage
import PIL.ImageDraw as _PILImageDraw
import PIL.ImageFont as _PILImageFont

KTOX_DIR = os.environ.get("KTOX_DIR", "/home/kali/KTOx")
FRAME_PATH = os.environ.get("KTOX_FRAME_PATH", "/dev/shm/ktox_last.jpg")

# ── Scale factor (uniform so KTOX's layout — including the on-screen keyboard
# — stays internally consistent) ──────────────────────────────────────────────
# Non-uniform scaling spread layouts out horizontally but broke the on-screen
# keyboard (its grid assumes a square aspect; with x*3.75/y*2.5 the keys
# spread off-canvas and only a few were visible). Uniform 2.5x = 320x320
# native render, centered on the 480x320 panel with 80px bars.
SCALE_X = 2.5
SCALE_Y = 2.5
FONT_SCALE = 2.5
CANVAS_W = int(128 * SCALE_X)   # 320
CANVAS_H = int(128 * SCALE_Y)   # 320


# ── 1. Fake LCD module ────────────────────────────────────────────────────────
class _FakeLCD:
    """Mimics LCD_1in44.LCD; writes the rendered PIL frame to /dev/shm."""

    SCAN_DIR_DFT = 0

    def __init__(self):
        # KTOX reads these and uses them as the canvas dimensions when it
        # allocates Image.new("RGB", (LCD.width, LCD.height), ...).
        self.width = CANVAS_W
        self.height = CANVAS_H

    def LCD_Init(self, scan_dir=0):
        try:
            _PILImage.new("RGB", (self.width, self.height), "#000000").save(
                FRAME_PATH, "JPEG", quality=85
            )
        except Exception:
            pass

    def LCD_ShowImage(self, image, x=0, y=0):
        # The on-screen keyboard renders to its own 128x128 canvas at native
        # resolution (we temporarily un-scale Draw/Font while it runs — see
        # the DarkSecKeyboard wrappers below). Upscale that 128 frame here to
        # match the rest of the UI's 320x320 output so the mirror gets a
        # consistent source size and the keyboard fills the visible area.
        if image.size != (CANVAS_W, CANVAS_H):
            try:
                image = image.resize((CANVAS_W, CANVAS_H), _PILImage.NEAREST)
            except Exception:
                pass
        tmp = FRAME_PATH + ".tmp"
        try:
            image.save(tmp, "JPEG", quality=88)
            os.replace(tmp, FRAME_PATH)
        except Exception:
            pass

    def LCD_Clear(self):
        pass

    def reset(self):
        pass


_fake_lcd_mod = types.ModuleType("LCD_1in44")
_fake_lcd_mod.LCD = _FakeLCD
_fake_lcd_mod.SCAN_DIR_DFT = 0
_fake_lcd_mod.set_screen_rotation = lambda *a, **k: None
sys.modules["LCD_1in44"] = _fake_lcd_mod

_fake_cfg = types.ModuleType("LCD_Config")
_fake_cfg.Driver_Delay_ms = lambda ms: time.sleep(ms / 1000.0)
sys.modules["LCD_Config"] = _fake_cfg


# ── 2. ImageFont.truetype: load every font at FONT_SCALE x requested size ───
_orig_truetype = _PILImageFont.truetype


def _scaled_truetype(font, size=10, *args, **kwargs):
    return _orig_truetype(font, max(1, int(size * FONT_SCALE)), *args, **kwargs)


_PILImageFont.truetype = _scaled_truetype


# ── 2b. ImageDraw.Draw: wrap every Draw with per-axis coord-scaling proxy ────
_orig_Draw = _PILImageDraw.Draw


def _sx(v):
    return int(v * SCALE_X)


def _sy(v):
    return int(v * SCALE_Y)


def _scale_value(v):
    """Scale coords. Lists of (x,y) tuples scale per-axis. Flat sequences are
    treated as alternating x,y,x,y. Single ints aren't dimensions in any
    coord context PIL takes, so leave them."""
    if v is None:
        return v
    if isinstance(v, (list, tuple)):
        if v and isinstance(v[0], (list, tuple)):
            return type(v)((_sx(p[0]), _sy(p[1])) for p in v)
        # Flat: [x0, y0, x1, y1, ...] — scale alternating
        return type(v)(_sx(c) if i % 2 == 0 else _sy(c) for i, c in enumerate(v))
    return v


def _scale_width(kw):
    # Line widths scale uniformly with the smaller axis (else lines look
    # stretched). Same as fonts — preserve visual weight.
    if "width" in kw and isinstance(kw["width"], (int, float)):
        kw = dict(kw)
        kw["width"] = max(1, int(kw["width"] * FONT_SCALE))
    return kw


class _ScaledDraw:
    """Proxy around PIL.ImageDraw.ImageDraw — scales all coord and width args
    by SCALE before delegating, and returns text-measurement results
    DIVIDED by SCALE so KTOX's 128-base centering arithmetic keeps working."""

    __slots__ = ("_d",)

    def __init__(self, im, *args, **kwargs):
        self._d = _orig_Draw(im, *args, **kwargs)

    # --- coord-scaling draw methods ------------------------------------------
    def rectangle(self, xy, *a, **kw):
        return self._d.rectangle(_scale_value(xy), *a, **_scale_width(kw))

    def rounded_rectangle(self, xy, *a, radius=0, **kw):
        return self._d.rounded_rectangle(
            _scale_value(xy), *a,
            radius=int(radius * FONT_SCALE) if isinstance(radius, (int, float)) else radius,
            **_scale_width(kw),
        )

    def line(self, xy, *a, **kw):
        return self._d.line(_scale_value(xy), *a, **_scale_width(kw))

    def ellipse(self, xy, *a, **kw):
        return self._d.ellipse(_scale_value(xy), *a, **_scale_width(kw))

    def arc(self, xy, *a, **kw):
        return self._d.arc(_scale_value(xy), *a, **_scale_width(kw))

    def chord(self, xy, *a, **kw):
        return self._d.chord(_scale_value(xy), *a, **_scale_width(kw))

    def pieslice(self, xy, *a, **kw):
        return self._d.pieslice(_scale_value(xy), *a, **_scale_width(kw))

    def polygon(self, xy, *a, **kw):
        return self._d.polygon(_scale_value(xy), *a, **kw)

    def point(self, xy, *a, **kw):
        return self._d.point(_scale_value(xy), *a, **kw)

    def text(self, xy, text, *a, **kw):
        return self._d.text((_sx(xy[0]), _sy(xy[1])), text, *a, **kw)

    def multiline_text(self, xy, text, *a, **kw):
        return self._d.multiline_text((_sx(xy[0]), _sy(xy[1])), text, *a, **kw)

    # --- measurement results returned in *1x* coords -------------------------
    def textbbox(self, xy, text, *a, **kw):
        # Input xy is 1x; we draw at scaled. Result bbox must come back at
        # 1x so source-level centering math (e.g. (128-w)//2) stays right.
        bbox = self._d.textbbox((_sx(xy[0]), _sy(xy[1])), text, *a, **kw)
        # bbox = (left, top, right, bottom) — x-coords / SCALE_X, y / SCALE_Y
        return (int(bbox[0] / SCALE_X), int(bbox[1] / SCALE_Y),
                int(bbox[2] / SCALE_X), int(bbox[3] / SCALE_Y))

    def textlength(self, text, *a, **kw):
        # textlength is a horizontal extent — divide by SCALE_X.
        return int(self._d.textlength(text, *a, **kw) / SCALE_X)

    # --- forward anything we forgot ------------------------------------------
    def __getattr__(self, name):
        return getattr(self._d, name)


_PILImageDraw.Draw = _ScaledDraw


# ── 3. Load KTOX with all the fakes/wrappers in place ────────────────────────
sys.path.insert(0, KTOX_DIR)
sys.path.insert(0, os.path.join(KTOX_DIR, "ktox_pi"))

import ktox_device  # noqa: E402

# ── 3b. Disable scaling during DarkSecKeyboard ────────────────────────────────
# The on-screen keyboard (used for WiFi password entry, etc.) draws in PIXEL
# coordinates against its own canvas, not in KTOX's 128-base logical coords.
# If our 2.5x ScaledDraw proxy stays active during keyboard rendering, every
# coord lands 2.5x off where it should and only the top-left 4 keys are
# visible. Wrap __init__/run on the keyboard class to swap back to the
# *original* Draw + truetype for its lifetime, then restore ours on exit.
# The keyboard's resulting 128x128 frame gets upscaled to CANVAS_W in
# FakeLCD.LCD_ShowImage above so it visually matches the rest of the UI.
import _darksec_keyboard  # noqa: E402

_kb_orig_init = _darksec_keyboard.DarkSecKeyboard.__init__
_kb_orig_run = _darksec_keyboard.DarkSecKeyboard.run


def _kb_unscale():
    _PILImageDraw.Draw = _orig_Draw
    _PILImageFont.truetype = _orig_truetype


def _kb_rescale():
    _PILImageDraw.Draw = _ScaledDraw
    _PILImageFont.truetype = _scaled_truetype


def _kb_patched_init(self, *args, **kwargs):
    _kb_unscale()
    try:
        return _kb_orig_init(self, *args, **kwargs)
    except Exception:
        _kb_rescale()
        raise


def _kb_patched_run(self, *args, **kwargs):
    try:
        return _kb_orig_run(self, *args, **kwargs)
    finally:
        _kb_rescale()


_darksec_keyboard.DarkSecKeyboard.__init__ = _kb_patched_init
_darksec_keyboard.DarkSecKeyboard.run = _kb_patched_run


# ── 3c. Hide KTOX's duplicated top bar ───────────────────────────────────────
# KTOX's _draw_toolbar() paints "<temp>C  KTOx_Pi  v<version>" at the top of
# every frame. With the compositor mirror, the right sidebar already shows
# clock, temp, version, etc — the in-frame bar is duplicate clutter that also
# steals ~28px of vertical space (scaled). Replace it with a thin red accent
# line so the menu has more room and there's still a top boundary marker.
def _ktox_quiet_toolbar():
    try:
        # Thin red rule under where the old toolbar lived. No text, no fill.
        ktox_device.draw.line([(0, 10), (128, 10)],
                              fill=ktox_device.color.border, width=1)
    except Exception:
        pass

ktox_device._draw_toolbar = _ktox_quiet_toolbar


ktox_device.PINS = {
    "KEY_UP_PIN":     5,
    "KEY_DOWN_PIN":   6,
    "KEY_LEFT_PIN":  13,
    "KEY_RIGHT_PIN": 19,
    "KEY_PRESS_PIN": 26,   # A button = OK/select
    "KEY1_PIN":      12,   # B = back
    "KEY2_PIN":      21,   # START = home
    "KEY3_PIN":       4,   # SELECT = stop/exit
}

# ── 3d. L/R shoulder buttons → page up / page down ───────────────────────────
# L=23, R=18 aren't in KTOX's PINS dict (it only knows the 8 SPI-HAT names)
# so they'd be wasted. Run a small polling thread that, on press, enqueues
# 6 synthetic UP/DOWN events directly into ktox_input's queue — so any list
# menu scrolls a page at a time. Works because ktox_device.getButton checks
# the virtual queue first and treats virtual presses identically to GPIO.
import threading  # noqa: E402

L_PIN, R_PIN = 23, 18
PAGE_STEP = 6        # how many UP/DOWN events one L/R press generates
LR_DEBOUNCE = 0.30   # seconds between accepted presses


def _lr_pager_loop():
    try:
        import RPi.GPIO as GPIO
        sys.path.insert(0, os.path.join(KTOX_DIR, "ktox_pi"))
        import ktox_input
    except Exception as e:
        print(f"[lr-pager] disabled: {e}", file=sys.stderr)
        return

    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(L_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(R_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    last_press = 0.0
    prev_l = prev_r = 1
    while True:
        try:
            now = time.time()
            l_now = GPIO.input(L_PIN)
            r_now = GPIO.input(R_PIN)
            if l_now == 0 and prev_l == 1 and (now - last_press) > LR_DEBOUNCE:
                last_press = now
                for _ in range(PAGE_STEP):
                    try:
                        ktox_input._q.put_nowait("KEY_UP_PIN")
                    except Exception:
                        break
            elif r_now == 0 and prev_r == 1 and (now - last_press) > LR_DEBOUNCE:
                last_press = now
                for _ in range(PAGE_STEP):
                    try:
                        ktox_input._q.put_nowait("KEY_DOWN_PIN")
                    except Exception:
                        break
            prev_l, prev_r = l_now, r_now
            time.sleep(0.02)
        except Exception:
            # Likely an exec_payload's GPIO.cleanup() between iterations.
            # Re-establish on next iteration.
            try:
                GPIO.setup(L_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
                GPIO.setup(R_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            except Exception:
                pass
            time.sleep(0.5)


threading.Thread(target=_lr_pager_loop, daemon=True, name="lr-pager").start()


# ── 3e. UI click sounds — emit button-event file for mirror to read ──────────
# The runner can't easily play audio (sudo+root → no pipewire session), but
# the mirror has the user's Wayland/pipewire session and can. We just write
# a 1-byte type code to /dev/shm/ktox_btn_evt each time a button registers;
# mirror polls the mtime and plays the corresponding click sound.
BTN_EVT_PATH = "/dev/shm/ktox_btn_evt"
BTN_TYPE = {
    "KEY_UP_PIN":     b"n",
    "KEY_DOWN_PIN":   b"n",
    "KEY_LEFT_PIN":   b"n",
    "KEY_RIGHT_PIN":  b"n",
    "KEY_PRESS_PIN":  b"c",   # confirm
    "KEY1_PIN":       b"b",   # back
    "KEY2_PIN":       b"h",   # home
    "KEY3_PIN":       b"x",   # stop/exit
}

_orig_getButton = ktox_device.getButton


def _getButton_with_evt(timeout=120):
    btn = _orig_getButton(timeout)
    if btn:
        code = BTN_TYPE.get(btn, b"n")
        try:
            with open(BTN_EVT_PATH, "wb") as f:
                f.write(code)
        except Exception:
            pass
    return btn


ktox_device.getButton = _getButton_with_evt

# ── Run boot() as if we owned the device ─────────────────────────────────────
import signal  # noqa: E402

if __name__ == "__main__":
    if os.geteuid() != 0:
        print("ktox_bigscreen_runner.py must run as root for GPIO access.",
              file=sys.stderr)
        sys.exit(1)
    signal.signal(signal.SIGINT, ktox_device._sig)
    signal.signal(signal.SIGTERM, ktox_device._sig)
    try:
        ktox_device.boot()
    except Exception as e:
        print(f"[ktox-neobox] Fatal: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            pass
