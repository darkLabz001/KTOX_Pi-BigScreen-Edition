# Display support plan

KTOX currently has a lot of payload/UI code that imports `LCD_1in44` directly and draws with 128x128 coordinates. To support more panels without rewriting every payload, we will keep that public API stable and move panel-specific behavior behind display profiles and drivers.

## Supported profile keys

| Profile | Hardware | Resolution | Transport | Driver direction |
| --- | --- | ---: | --- | --- |
| `ST7735_128` | Waveshare 1.44 inch LCD HAT | 128x128 | SPI | Existing `LCD_1in44` path |
| `ST7789_240` | Waveshare 1.3 inch 240x240 LCD HAT | 240x240 | SPI | Add an ST7789 driver behind the same `LCD_ShowImage` API |
| `MHS35_FB` | MHS 3.5 inch touch LCD | 480x320 | framebuffer/touch | Add a framebuffer renderer and touch input adapter |

## Migration approach

1. **Profile first.** `gui_conf.json` owns the selected `DISPLAY.type`, and `display_profiles.py` maps that key to size, controller, transport, touch capability, and the driver family.
2. **Scale existing UI.** Payloads that use `_display_helper.ScaledDraw` continue drawing in a 128-base coordinate system, while the helper scales coordinates and fonts to the active profile.
3. **Keep compatibility.** Existing payloads can continue importing `LCD_1in44` while we make that module a compatibility facade over ST7735, ST7789, and framebuffer backends.
4. **Split input from display.** Button GPIO and touch events should become input profiles, because the Waveshare joystick/buttons and MHS touchscreen are different devices.
5. **Add hardware smoke tests.** Each real panel needs a boot splash, color bars, rotation, and input test before it is marked production-ready.

## Configuration examples

```json
"DISPLAY": {
  "type": "ST7789_240"
}
```

```json
"DISPLAY": {
  "type": "MHS35_FB"
}
```

The default remains `ST7735_128` so existing Raspberry Pi Zero/Waveshare 1.44 inch setups keep working.
