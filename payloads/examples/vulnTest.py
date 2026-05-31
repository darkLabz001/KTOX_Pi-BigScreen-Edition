#!/usr/bin/env python3
"""
KTOx Payload – Vulnerability Assessment Suite
================================================
Automated network scanner + exploit suggester.
Scans hosts, fingerprints services, matches CVEs, suggests exploits.

Loot: /root/KTOx/loot/VulnScan/
"""

import os
import sys
import time
import json
import subprocess
import re
import threading
import socket
from datetime import datetime

# KTOx hardware
import RPi.GPIO as GPIO
import LCD_1in44
from PIL import Image, ImageDraw, ImageFont

# ----------------------------------------------------------------------
# Paths & config
# ----------------------------------------------------------------------
LOOT_DIR = "/root/KTOx/loot/VulnScan"
os.makedirs(LOOT_DIR, exist_ok=True)
REPORT = os.path.join(LOOT_DIR, f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
LOG = os.path.join(LOOT_DIR, "session.log")

# ----------------------------------------------------------------------
# LCD & GPIO
# ----------------------------------------------------------------------
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
FONT = font(9)
FONT_BOLD = font(10)

def wait_btn(timeout=0.1):
    start = time.time()
    while time.time() - start < timeout:
        for name, pin in PINS.items():
            if GPIO.input(pin) == 0:
                time.sleep(0.05)
                return name
        time.sleep(0.02)
    return None

def draw_menu(items, title="Vuln Scanner", selected=0, status=""):
    img = Image.new("RGB", (W, H), (10, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 13), fill=(139, 0, 0))
    d.text((4, 2), title[:20], font=FONT_BOLD, fill=(231, 76, 60))
    y = 16
    for i, item in enumerate(items[:6]):
        if i == selected:
            d.rectangle((0, y-1, W, y+9), fill=(60, 0, 0))
            d.text((4, y), f"> {item[:21]}", font=FONT, fill=(255, 255, 255))
        else:
            d.text((4, y), f"  {item[:21]}", font=FONT, fill=(171, 178, 185))
        y += 12
    if status:
        d.text((4, H-12), status[:23], font=FONT, fill=(192, 57, 43))
    else:
        d.text((4, H-12), "UP/DOWN OK  K1=Back K2=Refresh K3=Exit", font=FONT, fill=(192, 57, 43))
    LCD.LCD_ShowImage(img, 0, 0)

def show_message(msg, sub=""):
    img = Image.new("RGB", (W, H), (10, 0, 0))
    d = ImageDraw.Draw(img)
    d.text((10, 50), msg, font=FONT_BOLD, fill=(30, 132, 73))
    if sub:
        d.text((4, 65), sub[:22], font=FONT, fill=(113, 125, 126))
    LCD.LCD_ShowImage(img, 0, 0)
    time.sleep(1.5)

def show_progress(title, current, total):
    img = Image.new("RGB", (W, H), (10, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 13), fill=(139, 0, 0))
    d.text((4, 2), title[:20], font=FONT_BOLD, fill=(231, 76, 60))
    pct = int(current / total * 100) if total > 0 else 0
    bar_w = int(100 * pct / 100)
    d.rectangle((14, 40, 114, 50), fill=(34, 0, 0), outline=(192, 57, 43))
    d.rectangle((14, 40, 14+bar_w, 50), fill=(30, 132, 73))
    d.text((64, 35), f"{pct}%", font=FONT_BOLD, fill=(231, 76, 60), anchor="mm")
    LCD.LCD_ShowImage(img, 0, 0)

# ----------------------------------------------------------------------
# Utilities
# ----------------------------------------------------------------------
def run_cmd(cmd, timeout=60):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout + r.stderr
    except Exception as e:
        return -1, str(e)

def log(msg):
    with open(LOG, "a") as f:
        f.write(f"[{datetime.now().isoformat()}] {msg}\n")

def get_local_network():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip.rsplit('.', 1)[0] + ".0/24"
    except:
        return "192.168.1.0/24"

# ----------------------------------------------------------------------
# Discovery
# ----------------------------------------------------------------------
def discover_hosts():
    net = get_local_network()
    show_message("Discovering hosts", net)
    cmd = f"nmap -sn {net} -oG - | grep Up | cut -d' ' -f2 > {LOOT_DIR}/hosts.txt"
    run_cmd(cmd, timeout=30)
    with open(f"{LOOT_DIR}/hosts.txt", "r") as f:
        hosts = [line.strip() for line in f if line.strip()]
    log(f"Discovered {len(hosts)} hosts")
    return hosts

# ----------------------------------------------------------------------
# Service fingerprinting
# ----------------------------------------------------------------------
def scan_services(host):
    log(f"Scanning {host}")
    out_file = f"{LOOT_DIR}/nmap_{host.replace('.','_')}.xml"
    cmd = f"nmap -sV -O --script=banner -oX {out_file} {host}"
    run_cmd(cmd, timeout=90)
    # Parse XML for services
    import xml.etree.ElementTree as ET
    services = []
    try:
        tree = ET.parse(out_file)
        root = tree.getroot()
        for port in root.findall(".//port"):
            port_id = port.get("portid")
            state = port.find("state").get("state")
            if state != "open":
                continue
            service = port.find("service")
            if service is not None:
                name = service.get("name")
                product = service.get("product", "")
                version = service.get("version", "")
                services.append({
                    "port": port_id,
                    "service": name,
                    "product": product,
                    "version": version
                })
    except Exception as e:
        log(f"XML parse error: {e}")
    return services

# ----------------------------------------------------------------------
# Vulnerability matching
# ----------------------------------------------------------------------
def search_exploits(service_name, version):
    """Use searchsploit to find exploits for a service/version."""
    query = f"{service_name} {version}".strip()
    if not query:
        return []
    cmd = f"searchsploit --json {query}"
    rc, out = run_cmd(cmd, timeout=10)
    if rc != 0:
        return []
    try:
        data = json.loads(out)
        exploits = []
        for exp in data.get("RESULTS", []):
            exploits.append({
                "title": exp.get("Title", ""),
                "path": exp.get("Path", ""),
                "cve": exp.get("CVE", "")
            })
        return exploits[:5]
    except:
        return []

def check_known_cves(service_name, version):
    """Simple CVE pattern matching (placeholder for real CVE DB)."""
    # In a real implementation, you'd query a local CVE database.
    # For now, return common vulnerabilities.
    common = {
        "openssh": ["CVE-2021-28041", "CVE-2020-15778"],
        "apache": ["CVE-2021-41773", "CVE-2021-42013"],
        "nginx": ["CVE-2021-23017", "CVE-2020-11724"],
        "samba": ["CVE-2021-44142", "CVE-2020-1472"],
        "mysql": ["CVE-2021-27928", "CVE-2020-14812"],
    }
    for k, cv in common.items():
        if k in service_name.lower():
            return cv
    return []

# ----------------------------------------------------------------------
# Main scanning routine
# ----------------------------------------------------------------------
def run_full_assessment():
    hosts = discover_hosts()
    if not hosts:
        show_message("No hosts found")
        return

    report_data = {
        "timestamp": datetime.now().isoformat(),
        "targets": []
    }

    total = len(hosts)
    for i, host in enumerate(hosts):
        show_progress(f"Scanning {host}", i+1, total)
        services = scan_services(host)
        host_entry = {"ip": host, "services": []}
        for svc in services:
            exploits = search_exploits(svc["service"], svc["version"])
            cves = check_known_cves(svc["service"], svc["version"])
            host_entry["services"].append({
                "port": svc["port"],
                "service": svc["service"],
                "version": svc["version"],
                "exploits": exploits,
                "cves": cves
            })
        report_data["targets"].append(host_entry)
        log(f"Host {host}: {len(services)} services")

    with open(REPORT, "w") as f:
        json.dump(report_data, f, indent=2)
    show_message("Assessment complete", f"Report saved")
    return report_data

# ----------------------------------------------------------------------
# Display results
# ----------------------------------------------------------------------
def view_results():
    # Find latest report
    reports = sorted([f for f in os.listdir(LOOT_DIR) if f.startswith("report_") and f.endswith(".json")], reverse=True)
    if not reports:
        show_message("No reports found")
        return
    report_path = os.path.join(LOOT_DIR, reports[0])
    with open(report_path, "r") as f:
        data = json.load(f)

    # Build menu: host -> service list
    hosts = [f"{t['ip']} ({len(t['services'])} svc)" for t in data["targets"]]
    selected_host = 0
    while True:
        draw_menu(hosts, "Select Target", selected_host)
        btn = wait_btn(0.2)
        if btn == "UP":
            selected_host = (selected_host - 1) % len(hosts)
        elif btn == "DOWN":
            selected_host = (selected_host + 1) % len(hosts)
        elif btn == "OK":
            # Show services for this host
            target = data["targets"][selected_host]
            svc_items = [f"{s['port']} {s['service']} {s['version']}" for s in target["services"]]
            if not svc_items:
                show_message("No open ports")
                continue
            selected_svc = 0
            while True:
                draw_menu(svc_items, target["ip"], selected_svc)
                btn2 = wait_btn(0.2)
                if btn2 == "UP":
                    selected_svc = (selected_svc - 1) % len(svc_items)
                elif btn2 == "DOWN":
                    selected_svc = (selected_svc + 1) % len(svc_items)
                elif btn2 == "OK":
                    # Show exploits for this service
                    svc = target["services"][selected_svc]
                    exploits = svc.get("exploits", [])
                    if not exploits:
                        show_message("No exploits found")
                        continue
                    exp_items = [f"{e['title'][:20]}" for e in exploits]
                    selected_exp = 0
                    while True:
                        draw_menu(exp_items, f"Exploits for {svc['service']}", selected_exp)
                        btn3 = wait_btn(0.2)
                        if btn3 == "UP":
                            selected_exp = (selected_exp - 1) % len(exp_items)
                        elif btn3 == "DOWN":
                            selected_exp = (selected_exp + 1) % len(exp_items)
                        elif btn3 == "OK":
                            exp = exploits[selected_exp]
                            show_message(exp["title"][:20], exp["path"][:20])
                            time.sleep(2)
                        elif btn3 == "KEY1" or btn3 == "KEY3":
                            break
                elif btn2 == "KEY1" or btn2 == "KEY3":
                    break
        elif btn == "KEY1" or btn == "KEY3":
            break

# ----------------------------------------------------------------------
# Main menu
# ----------------------------------------------------------------------
def main():
    menu = ["1. Run Full Assessment", "2. View Last Report", "3. Quick Ping Sweep", "4. Exit"]
    idx = 0

    while True:
        draw_menu(menu, "Vuln Scanner", idx)
        btn = wait_btn(0.2)
        if btn == "UP":
            idx = (idx - 1) % len(menu)
        elif btn == "DOWN":
            idx = (idx + 1) % len(menu)
        elif btn == "OK":
            if idx == 0:
                run_full_assessment()
            elif idx == 1:
                view_results()
            elif idx == 2:
                net = get_local_network()
                show_message("Ping sweep", net)
                cmd = f"nmap -sn {net} -oG - | grep Up | cut -d' ' -f2"
                rc, out = run_cmd(cmd, timeout=30)
                hosts = [h for h in out.split() if h]
                show_message(f"Found {len(hosts)} hosts", "\n".join(hosts[:4]))
                time.sleep(2)
            elif idx == 3:
                break
        elif btn == "KEY3":
            break

    GPIO.cleanup()
    LCD.LCD_Clear()

if __name__ == "__main__":
    main()
