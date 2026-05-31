"""Display profile registry for KTOX screen support.

The rest of the project historically assumes a 128x128 Waveshare 1.44" ST7735
LCD.  This module centralizes panel metadata so renderers, asset optimizers, and
future hardware drivers can select the active display from ``gui_conf.json``
without hard-coding one controller everywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Dict, Iterable, Optional, Tuple


@dataclass(frozen=True)
class DisplayProfile:
    """Description of a supported display target."""

    key: str
    label: str
    width: int
    height: int
    controller: str
    transport: str
    driver: str
    touch: bool = False
    notes: str = ""

    @property
    def size(self) -> Tuple[int, int]:
        return self.width, self.height

    @property
    def scale_x(self) -> float:
        return self.width / 128

    @property
    def scale_y(self) -> float:
        return self.height / 128

    @property
    def scale(self) -> float:
        """Conservative uniform scale for fonts and line widths."""
        return min(self.scale_x, self.scale_y)


PROFILES: Dict[str, DisplayProfile] = {
    "ST7735_128": DisplayProfile(
        key="ST7735_128",
        label='Waveshare 1.44" LCD HAT',
        width=128,
        height=128,
        controller="ST7735S",
        transport="spi",
        driver="LCD_1in44",
        notes="Existing default KTOX panel and GPIO joystick/buttons.",
    ),
    "ST7789_240": DisplayProfile(
        key="ST7789_240",
        label='Waveshare 1.3" 240x240 LCD HAT',
        width=240,
        height=240,
        controller="ST7789",
        transport="spi",
        driver="LCD_ST7789",
        notes="SPI panel; keeps the same 128-base UI layout scaled to 240x240.",
    ),
    "MHS35_FB": DisplayProfile(
        key="MHS35_FB",
        label='MHS 3.5" Touch LCD',
        width=480,
        height=320,
        controller="framebuffer",
        transport="fbdev",
        driver="framebuffer",
        touch=True,
        notes="Framebuffer/touchscreen target; render via pygame/fbdev or kiosk WebUI.",
    ),
}

_ALIASES = {
    "waveshare_1in44": "ST7735_128",
    "waveshare_1in3": "ST7789_240",
    "waveshare_1_3": "ST7789_240",
    "mhs35": "MHS35_FB",
    "mhs_3_5": "MHS35_FB",
}


DEFAULT_PROFILE = "ST7735_128"


def config_paths() -> Iterable[str]:
    """Return config locations in lookup order."""
    env_path = os.environ.get("KTOX_GUI_CONF")
    if env_path:
        yield env_path
    here = os.path.dirname(os.path.abspath(__file__))
    yield os.path.join(here, "gui_conf.json")
    yield "/root/KTOx/gui_conf.json"


def normalize_profile_key(value: Optional[str]) -> str:
    """Normalize a user/config display key to a known profile key."""
    if not value:
        return DEFAULT_PROFILE
    raw = str(value).strip()
    if raw in PROFILES:
        return raw
    lowered = raw.lower().replace("-", "_").replace(" ", "_")
    return _ALIASES.get(lowered, DEFAULT_PROFILE)


def load_display_key(conf_path: Optional[str] = None) -> str:
    """Read the active display key from ``gui_conf.json``."""
    paths = [conf_path] if conf_path else list(config_paths())
    for path in paths:
        if not path or not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                conf = json.load(fh)
            display = conf.get("DISPLAY", {})
            return normalize_profile_key(display.get("type") or display.get("profile"))
        except Exception:
            return DEFAULT_PROFILE
    return DEFAULT_PROFILE


def get_display_profile(conf_path: Optional[str] = None) -> DisplayProfile:
    """Return the active display profile, falling back to the 128x128 panel."""
    return PROFILES[load_display_key(conf_path)]


def get_target_size(conf_path: Optional[str] = None) -> Tuple[int, int]:
    """Return ``(width, height)`` for the active display profile."""
    return get_display_profile(conf_path).size
