# M5Cardputer Quick Start

## TL;DR - Get it working in 30 seconds

### On KTOX_Pi:

```bash
cd /root/KTOX_Pi
sudo ./scripts/run_with_m5_support.sh
```

That's it. Frame capture and WebSocket server start automatically.

### On M5Cardputer:

Build and flash the M5Cardputer application:

```bash
# Navigate to M5Cardputer firmware
cd /home/user/KTOX_Pi/m5cardputer

# Build and upload (requires USB connection to M5Cardputer)
platformio run -e m5stack-cardputer --target upload

# Monitor serial output during setup
platformio run -e m5stack-cardputer --target monitor
```

Follow the on-device setup wizard to enter:
- WiFi SSID
- WiFi password  
- KTOX_Pi IP address (e.g., 192.168.0.50)
- Port (default 8765)

Device connects and streams automatically.

---

## Verify It's Working

```bash
# On KTOX_Pi, check frames are being captured:
watch -n 0.5 ls -lh /dev/shm/ktox_last.jpg
```

Timestamps should update every ~160ms (for 6 FPS). If they don't, see troubleshooting below.

---

## Adjusting Frame Rate

```bash
# Higher responsiveness (but more bandwidth)
sudo /root/KTOX_Pi/run_with_m5_support.sh 10

# Lower bandwidth (but more laggy)
sudo /root/KTOX_Pi/run_with_m5_support.sh 3

# Default
sudo /root/KTOX_Pi/run_with_m5_support.sh
```

---

## Troubleshooting

### "Frame file exists but not updating"

```bash
# Check if LCD is actually being used
ps aux | grep ktox

# Check file permissions
ls -l /dev/shm/ktox_last.jpg
chmod 666 /dev/shm/ktox_last.jpg
```

### "M5 can't connect to device_server"

```bash
# Verify WebSocket is running
netstat -tlnp | grep 8765

# Check firewall
sudo ufw allow 8765
```

### "High latency / lag"

```bash
# Use lower FPS
sudo /root/KTOX_Pi/run_with_m5_support.sh 3

# Check network ping time
ping YOUR_KTOX_IP
```

---

## How It Works

```
LCD Display → Saved as JPEG every 160ms → device_server reads → sends to M5 via WebSocket
```

**Key files:**
- `LCD_1in44.py` — Does the frame capture (lines 328-334)
- `device_server.py` — Streams frames to M5
- `scripts/run_with_m5_support.sh` — Startup with proper config
- `.env.frame_capture` — Environment variables
- `scripts/test_m5_setup.py` — Verify everything works

---

## Full Documentation

- **M5Cardputer Build & Deploy**: See `../m5cardputer/README.md` for complete build, upload, and troubleshooting guide
- **Frame Capture Setup**: See `M5_CARDPUTER_SETUP.md` for server-side configuration details
- **Integration Overview**: See `M5_INTEGRATION_VERIFICATION.md` for architecture and verification steps
