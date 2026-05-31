#!/usr/bin/env python3
"""
KTOx Payload – Controller Pairing Tool
--------------------------------------
Pair Bluetooth controllers (8BitDo, Xbox, etc.) using LCD + buttons.

Controls:
  UP/DOWN  = scroll devices
  OK       = pair/connect
  KEY1     = refresh scan
  KEY3     = exit
"""

import os
import time
import subprocess
import RPi.GPIO as GPIO
import LCD_1in44
from PIL import Image, ImageDraw, ImageFont

# ── CONFIG ─────────────────────────────
PINS = {
    "UP":6, "DOWN":19, "LEFT":5, "RIGHT":26,
    "OK":13, "KEY1":21, "KEY2":20, "KEY3":16
}

GPIO.setmode(GPIO.BCM)
for p in PINS.values():
    GPIO.setup(p, GPIO.IN, pull_up_down=GPIO.PUD_UP)

LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
WIDTH, HEIGHT = LCD.width, LCD.height

img = Image.new("RGB",(WIDTH,HEIGHT))
draw = ImageDraw.Draw(img)
font = ImageFont.load_default()

running = True

# ── HELPERS ────────────────────────────
def draw_screen(lines, title="PAIRING"):
    draw.rectangle((0,0,WIDTH,HEIGHT), fill=(10, 0, 0))
    draw.text((2,2), title, fill="#00FFAA", font=font)

    y = 16
    for line in lines[:8]:
        draw.text((2,y), line[:20], fill=(242, 243, 244), font=font)
        y += 12

    draw.text((2,HEIGHT-10),"OK=Select K3=Exit", fill=(113, 125, 126), font=font)
    LCD.LCD_ShowImage(img,0,0)

def get_button():
    for name,pin in PINS.items():
        if GPIO.input(pin)==0:
            time.sleep(0.15)
            return name
    return None

# ── BLUETOOTH ─────────────────────────
def bt_cmd(cmd):
    return subprocess.getoutput(f"bluetoothctl {cmd}")

def start_scan():
    bt_cmd("power on")
    bt_cmd("agent on")
    bt_cmd("default-agent")
    bt_cmd("discoverable on")
    bt_cmd("pairable on")
    bt_cmd("scan on")

def get_devices():
    out = bt_cmd("devices")
    devices = []
    for line in out.splitlines():
        parts = line.split(" ",2)
        if len(parts) >= 3:
            mac = parts[1]
            name = parts[2]
            devices.append((mac,name))
    return devices

def pair_device(mac):
    draw_screen(["Pairing...", mac])
    bt_cmd(f"pair {mac}")
    bt_cmd(f"trust {mac}")
    bt_cmd(f"connect {mac}")
    draw_screen(["Connected!", mac])
    time.sleep(2)

# ── MAIN LOOP ─────────────────────────
def main():
    cursor = 0

    draw_screen(["Starting Bluetooth..."])
    start_scan()
    time.sleep(2)

    while running:
        devices = get_devices()

        if not devices:
            draw_screen([
                "No devices found",
                "",
                "Put controller",
                "in pairing mode",
                "",
                "KEY1 = refresh"
            ])
        else:
            lines = []
            for i,(mac,name) in enumerate(devices[:8]):
                prefix = ">" if i==cursor else " "
                lines.append(f"{prefix}{name[:16]}")
            draw_screen(lines)

        btn = get_button()

        if btn == "KEY3":
            break

        elif btn == "UP":
            cursor = max(0, cursor-1)

        elif btn == "DOWN":
            cursor = min(len(devices)-1, cursor+1)

        elif btn == "KEY1":
            draw_screen(["Refreshing..."])
            start_scan()
            time.sleep(1)

        elif btn == "OK" and devices:
            mac,name = devices[cursor]
            pair_device(mac)

    bt_cmd("scan off")
    LCD.LCD_Clear()
    GPIO.cleanup()

if __name__ == "__main__":
    main()
