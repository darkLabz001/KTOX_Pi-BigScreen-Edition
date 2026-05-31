#!/usr/bin/env bash
# KTOX_Pi installer — NeoBoX Game HAT variant
# Pi 3B+ · Debian trixie · Waveshare Game HAT (480x320 HDMI + 12 GPIO buttons)
#
# Safe rewrite of wickednull/KTOX_Pi install.sh with these deltas:
#   - skip `dnsmasq` (auto-starts + binds :53, severs SSH — see neobox-dnsmasq-trap)
#   - skip autologin root tty1 (would fight labwc kiosk for `kali`)
#   - skip auto-reboot at end
#   - install to /home/kali/KTOx (not /root/KTOx) — we run as user `kali`
#   - only enable WS + WebUI systemd units; LCD UI launches from labwc autostart
#   - GPIO pull-ups set for all 12 Game HAT buttons (4,5,6,12,13,16,18,19,20,21,23,26)
#
# Run: sudo bash install-bigscreen.sh

set -euo pipefail
step()  { printf "\e[1;31m[KTOx]\e[0m %s\n" "$*"; }
info()  { printf "\e[1;32m[ ok ]\e[0m %s\n" "$*"; }
warn()  { printf "\e[1;33m[warn]\e[0m %s\n" "$*"; }
fail()  { printf "\e[1;31m[FAIL]\e[0m %s\n" "$*"; exit 1; }

[[ $EUID -ne 0 ]] && fail "Run as root: sudo bash install-bigscreen.sh"

FIRMWARE_DIR="$(cd "$(dirname "$0")" && pwd)"
KTOX_SRC="${FIRMWARE_DIR}/KTOX_Pi"        # clone of wickednull/KTOX_Pi
KTOX_DIR="/home/kali/KTOx"
KTOX_USER="kali"
KTOX_GROUP="kali"

[[ -d "$KTOX_SRC" ]] || fail "Expected upstream clone at $KTOX_SRC — run: git clone https://github.com/wickednull/KTOX_Pi.git $KTOX_SRC"

# ── Boot config ───────────────────────────────────────────────────────────────
step "Configuring boot params (SPI/I2C + GPIO pull-ups)..."
CFG=/boot/firmware/config.txt; [[ -f $CFG ]] || CFG=/boot/config.txt
info "Config: $CFG"
add_param() { grep -qE "^#?\\s*${1%=*}=" "$CFG" && sed -Ei "s|^#?\\s*${1%=*}=.*|$1|" "$CFG" || echo "$1" >> "$CFG"; }
add_param "dtparam=spi=on"
add_param "dtparam=i2c_arm=on"
add_param "dtparam=i2c1=on"
grep -qE "^dtoverlay=spi0-[12]cs" "$CFG" || echo "dtoverlay=spi0-2cs" >> "$CFG"
# 12-button Game HAT pull-ups (covers the original KTOX 8 plus B/SELECT/L/R extras)
GPIO_LINE='gpio=4,5,6,12,13,16,18,19,20,21,23,26=pu'
if ! grep -qF "$GPIO_LINE" "$CFG"; then
    # Remove the original KTOX 8-pin variant if it was added by upstream
    sed -i '/^gpio=6,19,5,26,13,21,20,16=pu$/d' "$CFG"
    printf "\n# Game HAT button pull-ups (NeoBoX layout)\n%s\n" "$GPIO_LINE" >> "$CFG"
    info "GPIO pull-ups set for 12 Game HAT pins"
fi

# ── Kernel modules ────────────────────────────────────────────────────────────
step "Loading kernel modules..."
for m in i2c-bcm2835 i2c-dev spi_bcm2835 spidev; do
    grep -qxF "$m" /etc/modules || echo "$m" >> /etc/modules
    modprobe "$m" 2>/dev/null || true
done

# ── APT packages ──────────────────────────────────────────────────────────────
step "Installing packages..."
apt-get update -qq

# Core deps (no dnsmasq — see header). Kali-only packages (responder, mdk4,
# impacket-scripts, enum4linux, ettercap-text-only) omitted; install manually
# if/when needed and you're prepared for them to fail.
apt-get install -y --no-install-recommends \
    python3 python3-pip python3-dev \
    python3-scapy python3-netifaces python3-pyudev python3-serial \
    python3-smbus python3-rpi.gpio python3-spidev python3-pil python3-numpy \
    python3-setuptools python3-cryptography python3-requests python3-websockets \
    python3-pygame \
    fonts-dejavu-core \
    nmap ncat tcpdump arp-scan dsniff php procps \
    aircrack-ng wireless-tools wpasupplicant iw \
    hcxtools hcxdumptool hostapd \
    hashcat john hydra sshpass smbclient snmp \
    openssh-server openssh-client autossh \
    net-tools ethtool git i2c-tools libglib2.0-dev || warn "Some packages failed (non-fatal)"

# Optional Kali-only packages — try, but don't fail
apt-get install -y --no-install-recommends \
    responder mitmproxy ettercap-text-only mdk4 impacket-scripts enum4linux 2>/dev/null \
    || warn "Some Kali-only packages unavailable on Debian (expected)"

# ── Pip packages ──────────────────────────────────────────────────────────────
step "Installing Python packages..."
pip3 install --break-system-packages rich flask websockets pillow spidev RPi.GPIO requests python-nmap evdev 2>/dev/null \
    || warn "pip install had warnings"

# ── Font Awesome ──────────────────────────────────────────────────────────────
step "Installing Font Awesome icons..."
FA=/usr/share/fonts/truetype/fontawesome/fa-solid-900.ttf
if [[ ! -f "$FA" ]]; then
    mkdir -p "$(dirname $FA)"
    wget -q "https://use.fontawesome.com/releases/v6.5.1/webfonts/fa-solid-900.ttf" -O "$FA" \
        && info "Font Awesome installed" || warn "FA download failed (non-fatal)"
fi

# ── KTOx files ────────────────────────────────────────────────────────────────
step "Installing KTOx to $KTOX_DIR..."
install -d -o "$KTOX_USER" -g "$KTOX_GROUP" "$KTOX_DIR"
install -d -o "$KTOX_USER" -g "$KTOX_GROUP" "$KTOX_DIR/loot/MITM" "$KTOX_DIR/loot/Nmap" "$KTOX_DIR/loot/payloads" "$KTOX_DIR/roms"

# Core system files
for f in ktox_device.py LCD_1in44.py LCD_Config.py display_profiles.py \
         _input_helper.py _display_helper.py _darksec_keyboard.py _debug_helper.py \
         _keyboard_integration_examples.py debug_keyboard.py hid_helper.py \
         device_server.py web_server.py nmap_parser.py gui_conf.json \
         discord_webhook.txt monitor_mode_helper.py navarro_engine.py \
         payload_compat.py scan.py spoof.py sitecustomize.py update_menu.py \
         ktox.py ktox_mitm.py ktox_advanced.py ktox_extended.py ktox_defense.py \
         ktox_stealth.py ktox_netattack.py ktox_wifi.py ktox_dashboard.py \
         ktox_repl.py ktox_config.py ktox_device_pi.py ktox_device_improved.py \
         ktox_device_root.py requirements.txt setup_loki.sh; do
    if [[ -f "$KTOX_SRC/$f" ]]; then
        install -m 0644 -o "$KTOX_USER" -g "$KTOX_GROUP" "$KTOX_SRC/$f" "$KTOX_DIR/$f" 2>/dev/null \
            || cp -p "$KTOX_SRC/$f" "$KTOX_DIR/" && chown "$KTOX_USER:$KTOX_GROUP" "$KTOX_DIR/$f"
    fi
done
chmod +x "$KTOX_DIR/ktox_device.py" 2>/dev/null || true
[[ -f "$KTOX_DIR/setup_loki.sh" ]] && chmod +x "$KTOX_DIR/setup_loki.sh"

# Directories (preserve perms via cp -a, then chown the tree)
for d in payloads web Responder DNSSpoof Icons scripts config deploy img \
         assets vendor wifi ktox_pi EXTENSIONS docs; do
    if [[ -d "$KTOX_SRC/$d" ]]; then
        cp -a "$KTOX_SRC/$d" "$KTOX_DIR/"
    fi
done
chown -R "$KTOX_USER:$KTOX_GROUP" "$KTOX_DIR"

# Python deps from KTOX requirements.txt
if [[ -f "$KTOX_DIR/requirements.txt" ]]; then
    pip3 install --break-system-packages -r "$KTOX_DIR/requirements.txt" 2>/dev/null || warn "requirements.txt pip install had warnings"
fi

# Init git for the OTA update flow
step "Configuring git for over-the-air updates..."
if [[ ! -d "$KTOX_DIR/.git" ]]; then
    sudo -u "$KTOX_USER" git -C "$KTOX_DIR" init -q
    sudo -u "$KTOX_USER" git -C "$KTOX_DIR" remote add origin https://github.com/wickednull/KTOx_Pi.git
    sudo -u "$KTOX_USER" git -C "$KTOX_DIR" checkout -b main 2>/dev/null || true
    sudo -u "$KTOX_USER" git -C "$KTOX_DIR" add -A 2>/dev/null || true
    sudo -u "$KTOX_USER" git -C "$KTOX_DIR" -c user.email="ktox@neobox" -c user.name="KTOx-NeoBoX" \
        commit -q -m "KTOx_Pi initial install $(date +%Y-%m-%d)" 2>/dev/null || true
    info "Git repo initialised"
fi

# Payload compat symlink
[[ ! -e "/home/kali/Raspyjack" ]] && ln -s "$KTOX_DIR" "/home/kali/Raspyjack" && chown -h "$KTOX_USER:$KTOX_GROUP" "/home/kali/Raspyjack"

# /root/KTOx symlink — ktox_device.py and many other modules have the path
# /root/KTOx HARDCODED (default.payload_path, default.config_file, LOG_FILE,
# AUTH_FILE, GAMES_*, etc.). Without this, _list_payloads returns 0 across
# all 21 categories and the Payloads menu shows "No payloads found" even
# though 364 .py files are sitting in $KTOX_DIR/payloads. The symlink is
# permanent, OTA-safe, and means we don't have to fork ktox_device.py.
rm -rf /root/KTOx 2>/dev/null   # might pre-exist as auto-created empty dir
ln -s "$KTOX_DIR" /root/KTOx
info "/root/KTOx → $KTOX_DIR symlink (covers hardcoded paths)"

# ── KTOX boot branding (replaces NeoBoX in three places) ──────────────────────
step "Installing KTOX boot branding (Plymouth + swaybg wallpaper)..."

# 1) Generate KTOX splash PNG via PIL (800x600, dark red bg, KTOX chroma-text)
sudo -u "$KTOX_USER" mkdir -p "$KTOX_DIR/assets"
sudo -u "$KTOX_USER" python3 - << PYEOF
from PIL import Image, ImageDraw, ImageFont
W, H = 800, 600
img = Image.new("RGB", (W, H), (5, 0, 0))
d = ImageDraw.Draw(img)
RED = (180, 8, 12)
L, INSET, T = 80, 24, 4
for x, y, dx, dy in [(INSET, INSET, 1, 1), (W-INSET, INSET, -1, 1),
                     (INSET, H-INSET, 1, -1), (W-INSET, H-INSET, -1, -1)]:
    d.line([(x, y), (x + dx*L, y)], fill=RED, width=T)
    d.line([(x, y), (x, y + dy*L)], fill=RED, width=T)
try:
    f_logo = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", 180)
    f_tag  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 28)
    f_foot = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 18)
except Exception:
    f_logo = f_tag = f_foot = ImageFont.load_default()
def centered(text, y, font, fill):
    bbox = d.textbbox((0,0), text, font=font); w = bbox[2]-bbox[0]
    d.text(((W-w)//2, y), text, font=font, fill=fill)
def chroma(text, y, font):
    bbox = d.textbbox((0,0), text, font=font); w = bbox[2]-bbox[0]
    x = (W-w)//2
    d.text((x-4, y), text, font=font, fill=(255,60,60))
    d.text((x+4, y), text, font=font, fill=(45,226,255))
    d.text((x,   y), text, font=font, fill=(240,240,255))
chroma("KTOX", H//2 - 110, f_logo)
d.rectangle([(W-360)//2, H//2+100, (W+360)//2, H//2+106], fill=(220, 35, 35))
centered("N E T W O R K  ·  C O N T R O L  ·  S U I T E",
         H//2 + 130, f_tag, (180,180,180))
centered("authorized eyes only · wickednull",
         H - 90, f_foot, (110, 95, 95))
img.save("$KTOX_DIR/assets/ktox_splash.png")
PYEOF
info "Generated $KTOX_DIR/assets/ktox_splash.png"

# 2) Plymouth ktox theme (used during kernel boot, before labwc)
mkdir -p /usr/share/plymouth/themes/ktox
cp "$KTOX_DIR/assets/ktox_splash.png" /usr/share/plymouth/themes/ktox/ktox.png
chmod 644 /usr/share/plymouth/themes/ktox/ktox.png
cat > /usr/share/plymouth/themes/ktox/ktox.plymouth << EOF
[Plymouth Theme]
Name=KTOX
Description=KTOX boot splash
ModuleName=script

[script]
ImageDir=/usr/share/plymouth/themes/ktox
ScriptFile=/usr/share/plymouth/themes/ktox/ktox.script
EOF
cat > /usr/share/plymouth/themes/ktox/ktox.script << 'EOF'
Window.SetBackgroundTopColor(0.02, 0.00, 0.00);
Window.SetBackgroundBottomColor(0.01, 0.00, 0.00);
logo.image = Image("ktox.png");
sw = Window.GetWidth();
sh = Window.GetHeight();
iw = logo.image.GetWidth();
ih = logo.image.GetHeight();
scale = sw / iw;
if (sh / ih < scale) { scale = sh / ih; }
logo.scaled = logo.image.Scale(iw * scale, ih * scale);
logo.sprite = Sprite(logo.scaled);
logo.sprite.SetX((sw - iw * scale) / 2);
logo.sprite.SetY((sh - ih * scale) / 2);
EOF
# Activate the theme + regenerate initramfs
if [[ -f /etc/plymouth/plymouthd.conf ]]; then
    sed -i "s/^Theme=.*/Theme=ktox/" /etc/plymouth/plymouthd.conf
    grep -q "^Theme=" /etc/plymouth/plymouthd.conf || echo "Theme=ktox" >> /etc/plymouth/plymouthd.conf
else
    printf "[Daemon]\nTheme=ktox\n" > /etc/plymouth/plymouthd.conf
fi
update-initramfs -u 2>&1 | tail -2 || warn "initramfs regen failed (Plymouth may keep prior theme)"
info "Plymouth theme set to ktox"

# 3) swaybg wallpaper (briefly visible between Plymouth and pygame mirror)
if [[ -f /etc/xdg/labwc/autostart ]]; then
    # Replace any reference to the old NeoBoX boot_splash with KTOX
    sed -i "s|/home/kali/neo/assets/backgrounds/boot_splash.png|$KTOX_DIR/assets/ktox_splash.png|" /etc/xdg/labwc/autostart
    info "labwc swaybg autostart now uses KTOX splash"
fi

# ── WebUI tokens ──────────────────────────────────────────────────────────────
step "Generating WebUI credentials..."
for f in "$KTOX_DIR/.webui_token" "$KTOX_DIR/.webui_session_secret"; do
    if [[ ! -s "$f" ]]; then
        sudo -u "$KTOX_USER" python3 -c "import secrets,pathlib; pathlib.Path('$f').write_text(secrets.token_urlsafe(48)+'\\n')"
        chmod 600 "$f"; chown "$KTOX_USER:$KTOX_GROUP" "$f"
        info "Created $f"
    fi
done

# ── WiFi pinning ──────────────────────────────────────────────────────────────
step "Pinning onboard WiFi interface name..."
for dev in /sys/class/net/wlan*; do
    [[ -e "$dev" ]] || continue
    DP=$(readlink -f "$dev/device" 2>/dev/null || true)
    if echo "$DP" | grep -q "mmc"; then
        MAC=$(cat "$dev/address" 2>/dev/null || true)
        [[ -n "$MAC" ]] && mkdir -p /etc/systemd/network && cat > /etc/systemd/network/10-ktox-wifi.link << LINK
[Match]
MACAddress=$MAC
[Link]
Name=wlan0
LINK
        info "Pinned onboard WiFi ($MAC) -> wlan0"
    fi
done

# ── Environment file (read by systemd units + shell sessions) ─────────────────
step "Setting up environment file..."
cat > /etc/profile.d/ktox.sh << ENVSCRIPT
# KTOx environment variables
export KTOX_DIR="$KTOX_DIR"
export KTOX_ROOT="$KTOX_DIR"
export KTOX_LOOT="$KTOX_DIR/loot"
export PYTHONPATH="$KTOX_DIR:\${PYTHONPATH}"
ENVSCRIPT
chmod 644 /etc/profile.d/ktox.sh
info "Environment file at /etc/profile.d/ktox.sh"

# ── Systemd: WS + WebUI only (LCD UI launches from labwc autostart) ───────────
step "Creating systemd services (WS + WebUI)..."

cat > /etc/systemd/system/ktox-device.service << UNIT
[Unit]
Description=KTOx WebSocket Server :8765
After=network.target
[Service]
Type=simple
WorkingDirectory=$KTOX_DIR
ExecStart=/usr/bin/python3 $KTOX_DIR/device_server.py
Restart=on-failure
User=root
Environment=PYTHONUNBUFFERED=1
Environment=KTOX_DIR=$KTOX_DIR
Environment=RJ_WS_TOKEN_FILE=$KTOX_DIR/.webui_token
Environment=RJ_WEB_AUTH_SECRET_FILE=$KTOX_DIR/.webui_session_secret
Environment=RJ_WEB_AUTH_FILE=$KTOX_DIR/.webui_auth.json
Environment=RJ_FRAME_PATH=/dev/shm/ktox_last.jpg
Environment=KTOX_FRAME_PATH=/dev/shm/ktox_last.jpg
[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/ktox-webui.service << UNIT
[Unit]
Description=KTOx WebUI HTTP Server :8080
After=ktox-device.service network-online.target
Wants=network-online.target
Requires=ktox-device.service
[Service]
Type=simple
WorkingDirectory=$KTOX_DIR
ExecStart=/usr/bin/python3 $KTOX_DIR/web_server.py
Restart=on-failure
RestartSec=3
User=root
Environment=PYTHONUNBUFFERED=1
Environment=KTOX_DIR=$KTOX_DIR
Environment=RJ_WS_TOKEN_FILE=$KTOX_DIR/.webui_token
Environment=RJ_WEB_AUTH_SECRET_FILE=$KTOX_DIR/.webui_session_secret
Environment=RJ_WEB_AUTH_FILE=$KTOX_DIR/.webui_auth.json
[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
# Disable any old neobox web service so the port isn't fought over
systemctl disable --now neo-web 2>/dev/null || true
systemctl enable ktox-device.service ktox-webui.service
info "2 services enabled (LCD UI handled by labwc autostart, not systemd)"

# ── Health check ──────────────────────────────────────────────────────────────
step "Health checks..."
python3 - << 'PY' || warn "Some Python imports failed"
for mod in ("RPi.GPIO","spidev","PIL","numpy","scapy","requests","websockets","pygame","evdev"):
    try:    __import__(mod.split('.')[0]); print(f"  ok  {mod}")
    except Exception as e: print(f"  FAIL  {mod}: {e}")
PY

echo
printf "\e[1;31m"
echo "╔══════════════════════════════════════════════╗"
echo "║   KTOx_Pi (NeoBoX variant) — Install Done    ║"
echo "╚══════════════════════════════════════════════╝"
printf "\e[0m"
echo
echo "  KTOX dir:  $KTOX_DIR  (owner: $KTOX_USER)"
echo "  Services:  ktox-device, ktox-webui  (enabled, start on next boot)"
echo "  LCD UI:    NOT started yet — needs runner + mirror + autostart swap."
echo
echo "  Next steps (do NOT reboot until these are done):"
echo "    1. Drop in ktox_bigscreen_runner.py + ktox_hdmi_mirror.py + launch-ktox.sh"
echo "    2. Swap ~/.config/labwc/autostart to call launch-ktox.sh"
echo "    3. THEN reboot."
echo
