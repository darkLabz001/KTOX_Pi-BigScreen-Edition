#!/usr/bin/env python3
"""
KTOx Payload – USB Rubber Ducky Injector
==========================================
- Ducky Script 3.0 interpreter (supports variables, loops, functions)
- Uses Pi Zero USB gadget mode (requires /dev/hidg0)
- LCD menu: list, preview, execute payloads
- Payloads: /root/KTOx/payloads/ducky/*.ds

Controls:
  UP/DOWN   – navigate payload list / scroll preview
  OK        – open preview / execute (with 3s countdown)
  KEY1      – refresh list
  KEY3      – back / exit
"""

import os
import sys
import time
import re
import struct
import random
import threading
from datetime import datetime

# ----------------------------------------------------------------------
# Hardware & LCD
# ----------------------------------------------------------------------
try:
    import RPi.GPIO as GPIO
    import LCD_1in44
    from PIL import Image, ImageDraw, ImageFont
    HAS_HW = True
except ImportError:
    HAS_HW = False
    print("KTOx hardware not found")
    sys.exit(1)

PINS = {
    "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26,
    "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16,
}
GPIO.setmode(GPIO.BCM)
for pin in PINS.values():
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
W, H = 128, 128

def font(size=9):
    try:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)
    except:
        return ImageFont.load_default()

f9 = font(9)
f11 = font(11)
f14 = font(14)

# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------
PAYLOADS_DIR = "/root/KTOx/payloads/ducky"
HID_DEVICE = "/dev/hidg0"
os.makedirs(PAYLOADS_DIR, exist_ok=True)

# ----------------------------------------------------------------------
# Ducky Script 3.0 Interpreter (adapted from original)
# ----------------------------------------------------------------------
# HID constants
MOD_LCTRL = 0x01
MOD_LSHIFT = 0x02
MOD_LALT = 0x04
MOD_LMETA = 0x08

_ASCII_MAP = {
    ' ': (0x00, 0x2c), '\t': (0x00, 0x2b), '\n': (0x00, 0x28),
    'a': (0x00, 0x04), 'b': (0x00, 0x05), 'c': (0x00, 0x06),
    'd': (0x00, 0x07), 'e': (0x00, 0x08), 'f': (0x00, 0x09),
    'g': (0x00, 0x0a), 'h': (0x00, 0x0b), 'i': (0x00, 0x0c),
    'j': (0x00, 0x0d), 'k': (0x00, 0x0e), 'l': (0x00, 0x0f),
    'm': (0x00, 0x10), 'n': (0x00, 0x11), 'o': (0x00, 0x12),
    'p': (0x00, 0x13), 'q': (0x00, 0x14), 'r': (0x00, 0x15),
    's': (0x00, 0x16), 't': (0x00, 0x17), 'u': (0x00, 0x18),
    'v': (0x00, 0x19), 'w': (0x00, 0x1a), 'x': (0x00, 0x1b),
    'y': (0x00, 0x1c), 'z': (0x00, 0x1d),
    'A': (0x02, 0x04), 'B': (0x02, 0x05), 'C': (0x02, 0x06),
    'D': (0x02, 0x07), 'E': (0x02, 0x08), 'F': (0x02, 0x09),
    'G': (0x02, 0x0a), 'H': (0x02, 0x0b), 'I': (0x02, 0x0c),
    'J': (0x02, 0x0d), 'K': (0x02, 0x0e), 'L': (0x02, 0x0f),
    'M': (0x02, 0x10), 'N': (0x02, 0x11), 'O': (0x02, 0x12),
    'P': (0x02, 0x13), 'Q': (0x02, 0x14), 'R': (0x02, 0x15),
    'S': (0x02, 0x16), 'T': (0x02, 0x17), 'U': (0x02, 0x18),
    'V': (0x02, 0x19), 'W': (0x02, 0x1a), 'X': (0x02, 0x1b),
    'Y': (0x02, 0x1c), 'Z': (0x02, 0x1d),
    '1': (0x00, 0x1e), '2': (0x00, 0x1f), '3': (0x00, 0x20),
    '4': (0x00, 0x21), '5': (0x00, 0x22), '6': (0x00, 0x23),
    '7': (0x00, 0x24), '8': (0x00, 0x25), '9': (0x00, 0x26),
    '0': (0x00, 0x27),
    '!': (0x02, 0x1e), '@': (0x02, 0x1f), '#': (0x02, 0x20),
    '$': (0x02, 0x21), '%': (0x02, 0x22), '^': (0x02, 0x23),
    '&': (0x02, 0x24), '*': (0x02, 0x25), '(': (0x02, 0x26),
    ')': (0x02, 0x27), '-': (0x00, 0x2d), '_': (0x02, 0x2d),
    '=': (0x00, 0x2e), '+': (0x02, 0x2e), '[': (0x00, 0x2f),
    '{': (0x02, 0x2f), ']': (0x00, 0x30), '}': (0x02, 0x30),
    '\\': (0x00, 0x31), '|': (0x02, 0x31), ';': (0x00, 0x33),
    ':': (0x02, 0x33), "'": (0x00, 0x34), '"': (0x02, 0x34),
    '`': (0x00, 0x35), '~': (0x02, 0x35), ',': (0x00, 0x36),
    '<': (0x02, 0x36), '.': (0x00, 0x37), '>': (0x02, 0x37),
    '/': (0x00, 0x38), '?': (0x02, 0x38),
}

_KEY_MAP = {
    "ENTER": (0x00, 0x28), "ESC": (0x00, 0x29), "BACKSPACE": (0x00, 0x2a),
    "TAB": (0x00, 0x2b), "SPACE": (0x00, 0x2c), "CAPSLOCK": (0x00, 0x39),
    "F1": (0x00, 0x3a), "F2": (0x00, 0x3b), "F3": (0x00, 0x3c),
    "F4": (0x00, 0x3d), "F5": (0x00, 0x3e), "F6": (0x00, 0x3f),
    "F7": (0x00, 0x40), "F8": (0x00, 0x41), "F9": (0x00, 0x42),
    "F10": (0x00, 0x43), "F11": (0x00, 0x44), "F12": (0x00, 0x45),
    "PRINTSCREEN": (0x00, 0x46), "SCROLLLOCK": (0x00, 0x47),
    "PAUSE": (0x00, 0x48), "INSERT": (0x00, 0x49), "HOME": (0x00, 0x4a),
    "PAGEUP": (0x00, 0x4b), "DELETE": (0x00, 0x4c), "END": (0x00, 0x4d),
    "PAGEDOWN": (0x00, 0x4e), "RIGHT": (0x00, 0x4f), "LEFT": (0x00, 0x50),
    "DOWN": (0x00, 0x51), "UP": (0x00, 0x52), "NUMLOCK": (0x00, 0x53),
    "MENU": (0x00, 0x65),
}

_MOD_MAP = {
    "CTRL": MOD_LCTRL, "CONTROL": MOD_LCTRL,
    "ALT": MOD_LALT, "SHIFT": MOD_LSHIFT,
    "GUI": MOD_LMETA, "WIN": MOD_LMETA, "WINDOWS": MOD_LMETA,
}
_COMBO_MOD_MAP = {
    "CTRL-ALT": MOD_LCTRL | MOD_LALT,
    "CTRL-SHIFT": MOD_LCTRL | MOD_LSHIFT,
    "ALT-SHIFT": MOD_LALT | MOD_LSHIFT,
    "GUI-SHIFT": MOD_LMETA | MOD_LSHIFT,
    "GUI-CTRL": MOD_LMETA | MOD_LCTRL,
    "CTRL-ALT-SHIFT": MOD_LCTRL | MOD_LALT | MOD_LSHIFT,
}

def _hid_report(mod, keycode):
    return struct.pack("8B", mod, 0, keycode, 0, 0, 0, 0, 0)
_RELEASE = _hid_report(0, 0)

def _send_key(fd, mod, keycode, delay=0.02):
    fd.write(_hid_report(mod, keycode))
    fd.flush()
    time.sleep(delay)
    fd.write(_RELEASE)
    fd.flush()
    time.sleep(delay)

def _type_string(fd, text):
    for ch in text:
        m = _ASCII_MAP.get(ch)
        if m:
            _send_key(fd, m[0], m[1])

class DuckyInterpreter:
    def __init__(self, status_cb=None):
        self.status_cb = status_cb
        self.vars = {}
        self.funcs = {}
        self.default_delay = 0
        self.fd = None
        self.break_flag = False

    def execute_file(self, path):
        if not os.path.exists(HID_DEVICE):
            return False, "HID not available.\nEnable gadget mode."
        try:
            self.fd = open(HID_DEVICE, "wb")
        except Exception as e:
            return False, f"Device error: {e}"
        try:
            with open(path, "r", encoding="utf-8") as f:
                source = f.read()
            tokens = self._tokenize(source)
            ast, funcs = self._parse(tokens)
            self.funcs = funcs
            self._exec_block(ast)
            self.fd.write(_RELEASE)
            self.fd.flush()
            self.fd.close()
            return True, "Payload executed."
        except Exception as e:
            self.fd.close()
            return False, str(e)[:60]

    def _tokenize(self, src):
        lines = []
        for i, raw in enumerate(src.splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith(("REM", "//", "#")):
                continue
            lines.append((i, line))
        return lines

    def _parse(self, lines):
        ast = []
        stack = [ast]
        funcs = {}
        i = 0
        while i < len(lines):
            lineno, line = lines[i]
            upper = line.upper()
            parts = line.split(None, 1)
            cmd = parts[0].upper()
            args = parts[1] if len(parts) > 1 else ""

            # Ignored compatibility
            if cmd in ("ATTACKMODE", "SAVE_HOST_KEYBOARD_LOCK_STATE",
                       "RESTORE_HOST_KEYBOARD_LOCK_STATE", "LED_OFF", "LED_R", "LED_G",
                       "WAIT_FOR_BUTTON_PRESS", "HOLD", "RELEASE"):
                i += 1
                continue

            # Variable declaration / assignment
            if cmd == "VAR":
                m = re.match(r'\$(\w+)\s*=\s*(.+)', args)
                if m:
                    stack[-1].append({"type": "VAR", "name": m.group(1), "expr": m.group(2)})
                i += 1
                continue
            if line.startswith("$"):
                m = re.match(r'\$(\w+)\s*=\s*(.+)', line)
                if m:
                    stack[-1].append({"type": "ASSIGN", "name": m.group(1), "expr": m.group(2)})
                i += 1
                continue

            # Control flow
            if cmd == "IF":
                m = re.match(r'IF\s*\((.+)\)\s*THEN', line, re.IGNORECASE)
                cond = m.group(1).strip() if m else args
                stack[-1].append({"type": "IF", "cond": cond})
                stack.append([])  # new block for THEN
                i += 1
                continue
            if upper == "ELSE IF":
                # Convert to nested IF inside ELSE
                m = re.match(r'ELSE\s+IF\s*\((.+)\)\s*THEN', line, re.IGNORECASE)
                cond = m.group(1).strip() if m else ""
                # Pop current THEN block, attach as branch
                body = stack.pop()
                parent = stack[-1]
                if parent and parent[-1]["type"] == "IF":
                    if "branches" not in parent[-1]:
                        parent[-1]["branches"] = [(parent[-1]["cond"], body)]
                        parent[-1]["cond"] = None
                    parent[-1]["branches"].append((cond, []))
                    stack.append(parent[-1]["branches"][-1][1])
                else:
                    # fallback
                    stack[-1].append({"type": "IF", "cond": cond})
                    stack.append([])
                i += 1
                continue
            if upper == "ELSE":
                # Pop current THEN block, add ELSE
                body = stack.pop()
                parent = stack[-1]
                if parent and parent[-1]["type"] == "IF":
                    if "branches" not in parent[-1]:
                        parent[-1]["branches"] = [(parent[-1]["cond"], body)]
                        parent[-1]["cond"] = None
                    parent[-1]["else"] = []
                    stack.append(parent[-1]["else"])
                else:
                    stack[-1].append({"type": "ELSE"})
                    stack.append([])
                i += 1
                continue
            if upper == "END_IF":
                body = stack.pop()
                parent = stack[-1]
                if parent and parent[-1]["type"] == "IF":
                    if "branches" in parent[-1]:
                        parent[-1]["branches"].append((None, body))
                    elif parent[-1].get("else") is not None:
                        parent[-1]["else"] = body
                    else:
                        parent[-1]["body"] = body
                i += 1
                continue
            if cmd == "WHILE":
                m = re.match(r'WHILE\s*\((.+)\)', line, re.IGNORECASE)
                cond = m.group(1).strip() if m else args
                stack[-1].append({"type": "WHILE", "cond": cond})
                stack.append([])
                i += 1
                continue
            if upper == "END_WHILE":
                body = stack.pop()
                parent = stack[-1]
                if parent and parent[-1]["type"] == "WHILE":
                    parent[-1]["body"] = body
                i += 1
                continue
            if upper == "BREAK":
                stack[-1].append({"type": "BREAK"})
                i += 1
                continue

            # Function definition
            if cmd == "FUNCTION":
                name = args.replace("()", "").strip()
                stack[-1].append({"type": "FUNCTION_DEF", "name": name})
                stack.append([])
                i += 1
                continue
            if upper == "END_FUNCTION":
                body = stack.pop()
                parent = stack[-1]
                if parent and parent[-1]["type"] == "FUNCTION_DEF":
                    funcs[parent[-1]["name"]] = body
                    parent.pop()  # remove FUNCTION_DEF node
                i += 1
                continue

            # Function call
            if line.endswith("()") and re.match(r'^\w+\(\)$', line):
                stack[-1].append({"type": "CALL", "name": line[:-2]})
                i += 1
                continue

            # Commands
            if cmd in ("STRING", "TYPE"):
                stack[-1].append({"type": "STRING", "text": args})
            elif cmd == "STRINGLN":
                stack[-1].append({"type": "STRINGLN", "text": args})
            elif cmd == "DELAY":
                stack[-1].append({"type": "DELAY", "ms": args})
            elif cmd == "DEFAULT_DELAY" or cmd == "DEFAULTDELAY":
                stack[-1].append({"type": "DEFAULT_DELAY", "ms": args})
            elif cmd in _KEY_MAP:
                stack[-1].append({"type": "KEY", "mod": 0, "key": cmd})
            else:
                # modifier combo
                handled = False
                for combo, mod_val in _COMBO_MOD_MAP.items():
                    if upper.startswith(combo):
                        rest = line[len(combo):].strip().upper()
                        stack[-1].append({"type": "KEY", "mod": mod_val, "key": rest or None})
                        handled = True
                        break
                if not handled and cmd in _MOD_MAP:
                    rest = args.upper().strip()
                    stack[-1].append({"type": "KEY", "mod": _MOD_MAP[cmd], "key": rest or None})
                else:
                    # Unknown command – treat as NOP
                    pass
            i += 1
        return ast, funcs

    def _exec_block(self, nodes):
        for node in nodes:
            if self.break_flag:
                break
            self._exec_node(node)

    def _exec_node(self, node):
        t = node["type"]
        if t == "NOP":
            pass
        elif t in ("VAR", "ASSIGN"):
            val = self._eval_expr(node["expr"])
            self.vars[node["name"]] = val
        elif t == "STRING":
            text = self._interpolate(node["text"])
            if self.status_cb:
                self.status_cb(f"TYPE: {text[:20]}")
            _type_string(self.fd, text)
            if self.default_delay:
                time.sleep(self.default_delay / 1000.0)
        elif t == "STRINGLN":
            text = self._interpolate(node["text"])
            _type_string(self.fd, text)
            _send_key(self.fd, 0, 0x28)
            if self.default_delay:
                time.sleep(self.default_delay / 1000.0)
        elif t == "DELAY":
            ms = self._eval_expr(node["ms"])
            try:
                time.sleep(float(ms) / 1000.0)
            except:
                pass
        elif t == "DEFAULT_DELAY":
            try:
                self.default_delay = int(self._eval_expr(node["ms"]))
            except:
                pass
        elif t == "KEY":
            mod = node["mod"]
            key = node["key"]
            if key and key in _KEY_MAP:
                kc = _KEY_MAP[key][1]
                _send_key(self.fd, mod, kc)
            elif key and len(key) == 1:
                m = _ASCII_MAP.get(key.lower())
                if m:
                    _send_key(self.fd, mod | m[0], m[1])
            elif mod:
                _send_key(self.fd, mod, 0)
            if self.default_delay:
                time.sleep(self.default_delay / 1000.0)
        elif t == "IF":
            cond = node.get("cond")
            if cond is None and "branches" in node:
                # already handled by IF_CHAIN, but we'll just skip
                pass
            else:
                if self._eval_cond(cond):
                    self._exec_block(node.get("body", []))
                else:
                    self._exec_block(node.get("else", []))
        elif t == "WHILE":
            max_iter = 100000
            c = 0
            while self._eval_cond(node["cond"]) and c < max_iter:
                self.break_flag = False
                self._exec_block(node["body"])
                if self.break_flag:
                    self.break_flag = False
                    break
                c += 1
        elif t == "BREAK":
            self.break_flag = True
        elif t == "CALL":
            if node["name"] in self.funcs:
                if self.status_cb:
                    self.status_cb(f"CALL {node['name']}()")
                self._exec_block(self.funcs[node["name"]])

    def _eval_expr(self, expr):
        expr = expr.strip()
        # Random
        m = re.match(r'RANDOM_INT\s+(\d+)\s+(\d+)', expr, re.IGNORECASE)
        if m:
            return random.randint(int(m.group(1)), int(m.group(2)))
        if expr.upper() == "RANDOM_CHAR":
            return random.choice("abcdefghijklmnopqrstuvwxyz")
        # Arithmetic on int variables
        m = re.match(r'\$(\w+)\s*([+\-*/])\s*(.+)', expr)
        if m:
            left = self.vars.get(m.group(1), 0)
            op = m.group(2)
            right = self._eval_expr(m.group(3))
            try:
                left = int(left)
                right = int(right)
                if op == "+": return left + right
                if op == "-": return left - right
                if op == "*": return left * right
                if op == "/" and right != 0: return left // right
            except:
                if op == "+": return str(left) + str(right)
            return left
        # Variable
        if expr.startswith("$"):
            return self.vars.get(expr[1:], "")
        # String literal
        if (expr.startswith('"') and expr.endswith('"')) or (expr.startswith("'") and expr.endswith("'")):
            return expr[1:-1]
        try:
            return int(expr)
        except:
            return expr

    def _interpolate(self, text):
        def repl(m):
            return str(self.vars.get(m.group(1), ""))
        return re.sub(r'\$(\w+)', repl, text)

    def _eval_cond(self, cond):
        if cond is None:
            return True
        cond = cond.strip()
        ops = [("==", lambda a, b: a == b),
               ("!=", lambda a, b: a != b),
               ("<=", lambda a, b: self._num(a) <= self._num(b)),
               (">=", lambda a, b: self._num(a) >= self._num(b)),
               ("<", lambda a, b: self._num(a) < self._num(b)),
               (">", lambda a, b: self._num(a) > self._num(b))]
        for op_str, fn in ops:
            if op_str in cond:
                parts = cond.split(op_str, 1)
                left = self._eval_expr(parts[0].strip())
                right = self._eval_expr(parts[1].strip())
                try:
                    return fn(left, right)
                except:
                    return False
        val = self._eval_expr(cond)
        return bool(val) and val not in (0, "0", "false", "FALSE", "")

    @staticmethod
    def _num(v):
        try:
            return int(v)
        except:
            return 0

# ----------------------------------------------------------------------
# LCD UI (list, preview, run)
# ----------------------------------------------------------------------
class DuckyUI:
    def __init__(self):
        self.payloads = []
        self.selected = 0
        self.scroll = 0
        self.preview_lines = []
        self.preview_scroll = 0
        self.state = "list"  # list, preview, run
        self.run_msg = ""
        self.run_ok = True
        self.running = False
        self.countdown = 0
        self.step_msg = ""

    def refresh_list(self):
        os.makedirs(PAYLOADS_DIR, exist_ok=True)
        files = [f for f in os.listdir(PAYLOADS_DIR) if f.endswith((".ds", ".payload"))]
        self.payloads = sorted(files)

    def load_preview(self):
        if not self.payloads:
            return
        path = os.path.join(PAYLOADS_DIR, self.payloads[self.selected])
        try:
            with open(path, "r", encoding="utf-8") as f:
                self.preview_lines = [l.rstrip() for l in f.readlines()]
        except:
            self.preview_lines = ["(error reading file)"]
        self.preview_scroll = 0

    def run_payload(self, status_cb):
        if not self.payloads:
            return False, "No payload selected"
        path = os.path.join(PAYLOADS_DIR, self.payloads[self.selected])
        interp = DuckyInterpreter(status_cb=status_cb)
        return interp.execute_file(path)

# ----------------------------------------------------------------------
# LCD drawing helpers
# ----------------------------------------------------------------------
def draw_screen(ui):
    img = Image.new("RGB", (W, H), "#0A0000")
    d = ImageDraw.Draw(img)
    # Header
    d.rectangle((0, 0, W, 17), fill="#8B0000")
    d.text((4, 3), "USB RUBBER DUCKY", font=f9, fill=(231, 76, 60))
    # HID status
    hid_ok = os.path.exists(HID_DEVICE)
    status_color = "#00FF00" if hid_ok else "#FF0000"
    status_text = "HID OK" if hid_ok else "NO HID"
    d.text((W - 50, 3), status_text, font=f9, fill=status_color)
    y = 20
    if ui.state == "list":
        # List payloads
        max_rows = 5
        start = ui.scroll
        for i in range(start, min(start + max_rows, len(ui.payloads))):
            name = ui.payloads[i][:-3] if ui.payloads[i].endswith(".ds") else ui.payloads[i][:-8]
            prefix = ">" if i == ui.selected else " "
            d.text((4, y), f"{prefix} {name[:20]}", font=f9, fill=(171, 178, 185))
            y += 12
        if not ui.payloads:
            d.text((4, y), "No payloads found", font=f9, fill=(113, 125, 126))
        d.text((4, H-12), "UP/DN OK K1=refresh K3=exit", font=f9, fill="#FF7777")
    elif ui.state == "preview":
        # Preview header
        name = ui.payloads[ui.selected][:-3] if ui.payloads[ui.selected].endswith(".ds") else ui.payloads[ui.selected][:-8]
        d.text((4, 20), f"PREVIEW: {name[:18]}", font=f9, fill=(171, 178, 185))
        # Preview content
        max_lines = 5
        visible = ui.preview_lines[ui.preview_scroll:ui.preview_scroll + max_lines]
        for line in visible:
            d.text((4, y), line[:23], font=f9, fill="#BBBBBB")
            y += 12
        d.text((4, H-12), "UP/DN scroll OK=run K3=back", font=f9, fill="#FF7777")
    elif ui.state == "run":
        # Running screen
        if ui.countdown > 0:
            d.text((4, 40), f"Running in {ui.countdown}...", font=f14, fill=(212, 172, 13))
        elif ui.running:
            d.text((4, 40), "Executing payload...", font=f9, fill=(30, 132, 73))
            if ui.step_msg:
                d.text((4, 55), ui.step_msg[:23], font=f9, fill=(171, 178, 185))
        else:
            # Done
            color = "#00FF00" if ui.run_ok else "#FF0000"
            d.text((4, 40), "DONE" if ui.run_ok else "FAILED", font=f14, fill=color)
            d.text((4, 60), ui.run_msg[:23], font=f9, fill=(171, 178, 185))
        d.text((4, H-12), "K3=back", font=f9, fill="#FF7777")
    LCD.LCD_ShowImage(img, 0, 0)

def wait_btn(timeout=0.1):
    start = time.time()
    while time.time() - start < timeout:
        for name, pin in PINS.items():
            if GPIO.input(pin) == 0:
                time.sleep(0.05)
                return name
        time.sleep(0.02)
    return None

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    ui = DuckyUI()
    ui.refresh_list()
    running = True

    while running:
        draw_screen(ui)
        btn = wait_btn(0.2)
        if ui.state == "list":
            if btn == "KEY3":
                break
            elif btn == "KEY1":
                ui.refresh_list()
                ui.selected = 0
                ui.scroll = 0
            elif btn == "UP" and ui.selected > 0:
                ui.selected -= 1
                if ui.selected < ui.scroll:
                    ui.scroll = ui.selected
            elif btn == "DOWN" and ui.selected < len(ui.payloads) - 1:
                ui.selected += 1
                if ui.selected >= ui.scroll + 5:
                    ui.scroll = ui.selected - 4
            elif btn == "OK" and ui.payloads:
                ui.load_preview()
                ui.state = "preview"
        elif ui.state == "preview":
            if btn == "KEY3":
                ui.state = "list"
            elif btn == "UP" and ui.preview_scroll > 0:
                ui.preview_scroll -= 1
            elif btn == "DOWN" and ui.preview_scroll < len(ui.preview_lines) - 5:
                ui.preview_scroll += 1
            elif btn == "OK":
                ui.state = "run"
                ui.countdown = 3
                ui.running = True
                ui.run_ok = True
                ui.run_msg = ""
                ui.step_msg = ""
                # Start countdown and execution in background
                def exec_thread():
                    for i in range(3, 0, -1):
                        ui.countdown = i
                        time.sleep(1)
                    ui.countdown = 0
                    ok, msg = ui.run_payload(lambda s: setattr(ui, 'step_msg', s))
                    ui.run_ok = ok
                    ui.run_msg = msg
                    ui.running = False
                threading.Thread(target=exec_thread, daemon=True).start()
        elif ui.state == "run":
            if btn == "KEY3" and not ui.running:
                ui.state = "list"
        time.sleep(0.05)

    GPIO.cleanup()
    LCD.LCD_Clear()
    sys.exit(0)

if __name__ == "__main__":
    # Ensure HID gadget is enabled (user must enable it first)
    if not os.path.exists(HID_DEVICE):
        print("\nHID gadget not found. Run this to enable:\n")
        print("  sudo modprobe g_hid")
        print("  echo 'g_hid' | sudo tee /etc/modules-load.d/g_hid.conf\n")
        print("Then reboot and run this payload again.\n")
        time.sleep(5)
        sys.exit(1)
    main()
