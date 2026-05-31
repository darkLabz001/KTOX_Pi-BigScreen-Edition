"""
Display helper for payloads – automatic 128-base coordinate scaling.

Usage in a payload:
    from _display_helper import ScaledDraw, scaled_font

    img = Image.new("RGB", (WIDTH, HEIGHT), (10, 0, 0))
    d = ScaledDraw(img)           # drop-in replacement for ImageDraw.Draw
    font = scaled_font()          # readable font for current resolution

All pixel coordinates passed to d.text(), d.rectangle(), d.line(), etc.
are automatically scaled from 128-base to the actual LCD resolution.
"""
from PIL import ImageDraw, ImageFont

from display_profiles import get_display_profile

# ---------------------------------------------------------------------------
# Detect target display and scale from the profile registry
# ---------------------------------------------------------------------------
_DISPLAY_PROFILE = get_display_profile()
LCD_SCALE_X = _DISPLAY_PROFILE.scale_x
LCD_SCALE_Y = _DISPLAY_PROFILE.scale_y
LCD_SCALE = _DISPLAY_PROFILE.scale
LCD_WIDTH, LCD_HEIGHT = _DISPLAY_PROFILE.size


def S(v):
    """Scale a 128-base pixel value to the current display resolution."""
    return int(v * LCD_SCALE)


def scaled_font(size=10):
    """Return a TrueType font scaled for the current display.

    *size* is the desired point size on a 128px screen; the returned font
    is proportionally larger on bigger panels.
    """
    scaled_size = S(size)
    try:
        return ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", scaled_size
        )
    except Exception:
        return ImageFont.load_default()


# ---------------------------------------------------------------------------
# ScaledDraw – wraps ImageDraw.Draw, scaling all 128-base coordinates
# ---------------------------------------------------------------------------
def _scale_point(pt):
    """Scale a 2-tuple or 2-list."""
    return (int(pt[0] * LCD_SCALE_X), int(pt[1] * LCD_SCALE_Y))


def _scale_coords(coords):
    """Scale a flat sequence of coordinates or a list of point tuples."""
    if not coords:
        return coords
    # list/tuple of 2-tuples: [(x,y), (x,y), ...]
    if isinstance(coords[0], (list, tuple)):
        return [_scale_point(p) for p in coords]
    # flat 4-value box: (x0, y0, x1, y1) or [x0, y0, x1, y1]
    if len(coords) == 4:
        return [
            int(coords[0] * LCD_SCALE_X),
            int(coords[1] * LCD_SCALE_Y),
            int(coords[2] * LCD_SCALE_X),
            int(coords[3] * LCD_SCALE_Y),
        ]
    # flat 2-value point
    if len(coords) == 2:
        return (int(coords[0] * LCD_SCALE_X), int(coords[1] * LCD_SCALE_Y))
    return coords


class ScaledDraw:
    """Drop-in replacement for ``ImageDraw.Draw`` that auto-scales coordinates.

    If ``LCD_SCALE == 1.0`` (128x128), no overhead is added.
    """

    def __init__(self, image):
        self._draw = ImageDraw.Draw(image)
        self._passthrough = LCD_SCALE == 1.0

    # -- Scaled drawing primitives ------------------------------------------

    def text(self, xy, text, fill=None, font=None, anchor=None, **kw):
        if not self._passthrough:
            xy = _scale_point(xy)
        self._draw.text(xy, text, fill=fill, font=font, anchor=anchor, **kw)

    def rectangle(self, xy, fill=None, outline=None, width=1, **kw):
        if not self._passthrough:
            xy = _scale_coords(xy)
            width = max(1, S(width)) if width > 1 else width
        self._draw.rectangle(xy, fill=fill, outline=outline, width=width, **kw)

    def line(self, xy, fill=None, width=1, **kw):
        if not self._passthrough:
            xy = _scale_coords(xy)
            width = max(1, S(width)) if width > 1 else width
        self._draw.line(xy, fill=fill, width=width, **kw)

    def ellipse(self, xy, fill=None, outline=None, width=1, **kw):
        if not self._passthrough:
            xy = _scale_coords(xy)
            width = max(1, S(width)) if width > 1 else width
        self._draw.ellipse(xy, fill=fill, outline=outline, width=width, **kw)

    def polygon(self, xy, fill=None, outline=None, **kw):
        if not self._passthrough:
            xy = _scale_coords(xy)
        self._draw.polygon(xy, fill=fill, outline=outline, **kw)

    def arc(self, xy, start, end, fill=None, width=1, **kw):
        if not self._passthrough:
            xy = _scale_coords(xy)
            width = max(1, S(width)) if width > 1 else width
        self._draw.arc(xy, start, end, fill=fill, width=width, **kw)

    def pieslice(self, xy, start, end, fill=None, outline=None, width=1, **kw):
        if not self._passthrough:
            xy = _scale_coords(xy)
            width = max(1, S(width)) if width > 1 else width
        self._draw.pieslice(xy, start, end, fill=fill, outline=outline, width=width, **kw)

    def textbbox(self, xy, text, font=None, **kw):
        if not self._passthrough:
            xy = _scale_point(xy)
        return self._draw.textbbox(xy, text, font=font, **kw)

    def textlength(self, text, font=None, **kw):
        return self._draw.textlength(text, font=font, **kw)

    # -- Passthrough for anything else --------------------------------------
    def __getattr__(self, name):
        return getattr(self._draw, name)
