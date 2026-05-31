# Complete M5Cardputer Setup Guide

This guide covers the complete end-to-end setup for using M5Stack Cardputer as a remote control for KTOX_Pi.

## Architecture Overview

```
┌─────────────────────────────────────┐
│  KTOX_Pi (Raspberry Pi)             │
├─────────────────────────────────────┤
│ LCD Display (128x128)               │
│  ↓                                  │
│ Frame Capture (LCD_1in44.py)        │
│  ↓                                  │
│ /dev/shm/ktox_last.jpg             │
│  ↓                                  │
│ device_server.py                    │
│  │                                  │
│  └─── WebSocket @ :8765             │
│       (sends base64 JPEG frames)    │
└─────────────────────────────────────┘
              ↑
              │ WiFi
              ↓
┌─────────────────────────────────────┐
│  M5Stack Cardputer (ESP32-S3)       │
├─────────────────────────────────────┤
│ 240x135 Display                     │
│ WebSocket Client (M5Cardputer.ino)  │
│ Keyboard Input Handler              │
│ JPEG Decoder & Display              │
│ Settings (SPIFFS)                   │
└─────────────────────────────────────┘
```

## Prerequisites

### KTOX_Pi Side

- Raspberry Pi with KTOX_Pi installed
- Python 3.6+ with websockets library
- Frame capture environment variables configured
- Network connectivity (WiFi or Ethernet)

### M5Cardputer Side

- M5Stack M5Cardputer device
- USB-C cable for programming
- PlatformIO IDE or CLI installed
- ESP32 Arduino framework
- Required Arduino libraries:
  - M5Cardputer @ ^1.0.3
  - WebSockets @ ^2.3.5 (links2004)
  - ArduinoJson @ ^6.19.4
  - TJpg_Decoder @ ^1.0.6

## Step-by-Step Setup

### Phase 1: Prepare KTOX_Pi Server

#### 1. Enable Frame Capture

Frame capture is built into KTOX_Pi. Configure it:

```bash
# Check current frame capture configuration
cat /home/user/KTOX_Pi/.env.frame_capture
```

Key variables:
- `RJ_FRAME_MIRROR=1` - Enable frame capture
- `RJ_FRAME_PATH=/dev/shm/ktox_last.jpg` - Where frames are saved
- `RJ_FRAME_FPS=6` - Frame rate (6 FPS recommended)
- `RJ_WS_HOST=0.0.0.0` - WebSocket bind address
- `RJ_WS_PORT=8765` - WebSocket port

#### 2. Start KTOX_Pi with M5 Support

```bash
sudo /home/user/KTOX_Pi/scripts/run_with_m5_support.sh [FPS]

# Examples:
sudo /home/user/KTOX_Pi/scripts/run_with_m5_support.sh 6      # Standard (6 FPS)
sudo /home/user/KTOX_Pi/scripts/run_with_m5_support.sh 10     # Responsive (10 FPS)
sudo /home/user/KTOX_Pi/scripts/run_with_m5_support.sh 3      # Low bandwidth (3 FPS)
```

#### 3. Verify Frame Capture is Working

```bash
# Check if frames are being created
ls -lh /dev/shm/ktox_last.jpg

# Monitor frame updates (should change every ~160ms for 6 FPS)
watch -n 0.5 ls -lh /dev/shm/ktox_last.jpg

# Check WebSocket is listening
netstat -tlnp | grep 8765
```

### Phase 2: Build M5Cardputer Firmware

#### 1. Install PlatformIO

```bash
# Via pip
pip install platformio

# Or use VS Code extension: Install PlatformIO IDE extension
```

#### 2. Navigate to M5Cardputer Project

```bash
cd /home/user/KTOX_Pi/m5cardputer
```

#### 3. Verify Build Configuration

Check `platformio.ini` is configured for M5Stack Cardputer:

```ini
[env:m5stack-cardputer]
platform = espressif32
board = m5stack-cores3
framework = arduino
```

#### 4. Compile Firmware

```bash
# Compile for M5Cardputer (no upload yet)
platformio run -e m5stack-cardputer

# Expected output:
# ========== [100%] Took X.XXs ==========
# Environment m5stack-cardputer: Build finished successfully.
```

### Phase 3: Flash M5Cardputer Device

#### 1. Connect M5Cardputer

- Connect M5Cardputer via USB-C cable to your computer
- LED should light up (power indicator)

#### 2. Identify USB Port

```bash
# List available ports
ls -la /dev/tty* | grep -E "USB|ttyACM|ttyUSB"

# Common ports:
# Linux: /dev/ttyACM0 or /dev/ttyUSB0
# macOS: /dev/tty.usbmodem* 
# Windows: COM3, COM4, etc.
```

#### 3. Upload Firmware

```bash
cd /home/user/KTOX_Pi/m5cardputer

# Upload to M5Cardputer
platformio run -e m5stack-cardputer --target upload

# Upload progress:
# Connecting... [1/4]
# Flashing firmware... [2/4]
# Verifying... [3/4]
# Resetting device... [4/4]
# Upload finished successfully.
```

#### 4. Monitor Initial Startup

```bash
# Connect to device serial output
platformio run -e m5stack-cardputer --target monitor

# Expected initial output:
# ================================
# KTOx Remote Control
# M5Cardputer Edition
# ================================
# [INFO] SPIFFS initialized
# [INFO] Settings loaded
# [INFO] Starting setup wizard...
```

### Phase 4: Configure M5Cardputer Device

After successful upload, M5Cardputer should display setup wizard:

#### Screen 1: WiFi SSID
- Type your WiFi network name
- Press ENTER to continue

#### Screen 2: WiFi Password
- Type your WiFi password (shown as *)
- Press ENTER to continue

#### Screen 3: KTOX_Pi Address
- Type KTOX_Pi IP address (e.g., 192.168.0.50)
- Press ENTER to continue

#### Screen 4: WebSocket Port
- Default is 8765 (usually correct)
- Press ENTER to continue

#### Screen 5: Authentication Token
- Optional - leave blank if not using authentication
- Press ENTER to proceed

#### Connection Phase
Device will:
1. Connect to WiFi (shows WiFi icon: 📶)
2. Establish WebSocket connection (shows connection status)
3. Start receiving frames
4. Show live video stream

### Phase 5: Verify End-to-End Connection

#### On KTOX_Pi Terminal

```bash
# Check WebSocket server is running
ps aux | grep device_server.py

# Monitor frame updates
watch -n 0.5 'stat /dev/shm/ktox_last.jpg | grep Modify'

# Check for connections in device_server output (if running in foreground)
# Should see: "[WebSocket] Client connected from <IP>"
```

#### On M5Cardputer Display

```
Expected display output:
┌────────────────────────┐
│                        │
│  [Live video stream]   │
│   (KTOX LCD display)   │
│                        │
├────────────────────────┤
│[●] 42 frames | FPS:5.8 │ (green ● = connected)
│M:Menu H:Config         │
└────────────────────────┘
```

#### Status Indicators

- **Connected (●)**: Device is connected to WebSocket and receiving frames
- **Disconnected (○)**: Device lost connection (will auto-reconnect)
- **Frame Count**: Number of frames received
- **FPS**: Actual frame rate being displayed

## Usage

### Main Operations

Press `M` from stream view to open main menu with options:
- Reconnaissance (ARP scans, host discovery, port scans)
- Offensive Attacks (DoS, ARP poisoning)
- Defensive/MITM (SSL stripping, DNS spoofing)
- WiFi Attacks (deauth, handshake capture)
- System Tools (status, logs, loot management)
- Settings (configuration menu)

### Key Controls

| Key | Action |
|-----|--------|
| `M` | Open/close main menu |
| `H` | Open settings/configuration |
| `T` | Set target IP address |
| `?` | Show help screen |
| Arrow keys / WASD | Navigate menu |
| Space / Enter | Select menu item |
| Q / Esc | Go back |

## Troubleshooting

### No Frames Displaying

**Problem**: M5 screen shows no video

**Solutions**:
```bash
# 1. Verify frames are being captured on KTOX_Pi
ls -lh /dev/shm/ktox_last.jpg

# 2. Check timestamps are changing
watch -n 0.5 stat /dev/shm/ktox_last.jpg | grep Modify

# 3. Verify device_server is running
ps aux | grep device_server.py

# 4. Check WebSocket is listening
netstat -tlnp | grep 8765

# 5. Test frame validity
file /dev/shm/ktox_last.jpg  # Should show "JPEG image data"

# 6. Check frame permissions
ls -l /dev/shm/ktox_last.jpg  # Should be readable
```

### WiFi Connection Fails

**Problem**: M5 can't connect to WiFi network

**Solutions**:
- Verify WiFi SSID spelling (case-sensitive)
- Ensure WiFi password is correct
- Check WiFi network is 2.4GHz (M5 doesn't support 5GHz)
- Move M5 closer to WiFi router
- Restart both M5 and WiFi router
- Clear stored settings: Delete `/settings.json` from M5 SPIFFS

### WebSocket Connection Fails

**Problem**: M5 connects to WiFi but not to device_server

**Solutions**:
```bash
# 1. Verify KTOX_Pi address is correct
ping YOUR_KTOX_IP

# 2. Check device_server is running
ps aux | grep device_server.py

# 3. Ensure port 8765 is open
sudo ufw allow 8765

# 4. Verify from M5 serial monitor
# Should show: "Connecting to WebSocket..."
# Then: "WebSocket connected" or error

# 5. Try manual WebSocket test from KTOX_Pi
python3 -c "
import asyncio, websockets, json
async def test():
    async with websockets.connect('ws://localhost:8765') as ws:
        msg = await ws.recv()
        print('Connected!')
asyncio.run(test())
"
```

### Laggy/High Latency Display

**Problem**: Video seems delayed or choppy

**Solutions**:
```bash
# Reduce frame rate
sudo /home/user/KTOX_Pi/scripts/run_with_m5_support.sh 3

# Check WiFi signal
# From M5: Press 'H' → view WiFi strength

# Monitor actual latency
ping -c 10 YOUR_KTOX_IP  # Should be <100ms
```

### Compilation Errors

**Problem**: `platformio run` fails with errors

**Solutions**:
```bash
# Update PlatformIO
platformio update

# Clean and rebuild
cd /home/user/KTOX_Pi/m5cardputer
platformio run -e m5stack-cardputer --target clean
platformio run -e m5stack-cardputer

# Delete build artifacts
rm -rf .pio .git/lfs

# Check board definition
platformio boards | grep -i cardputer
```

### Device Hangs or Crashes

**Problem**: M5 freezes, reboots, or doesn't respond

**Solutions**:
```bash
# Hard reset M5
# Press and hold the reset button (back of device) for 3 seconds

# Check serial output for errors
platformio run -e m5stack-cardputer --target monitor

# If SPIFFS is corrupted:
# 1. Upload firmware: platformio run -e m5stack-cardputer --target upload
# 2. Let it initialize SPIFFS (takes ~30 seconds)
```

## Performance Optimization

### Frame Rate Tuning

- **3 FPS**: Very low bandwidth (~8 KB/s), more latency
- **6 FPS**: Balanced (recommended) (~16 KB/s)
- **10 FPS**: Higher responsiveness (~27 KB/s)
- **15+ FPS**: Overkill, minimal improvement

### Bandwidth Estimation

```
Bandwidth = Frame_Size × FPS
Frame_Size ≈ 4-8 KB (typical JPEG at quality 75)

Examples:
- 6 FPS × 5 KB = 30 KB/s
- 10 FPS × 6 KB = 60 KB/s
```

### Power Consumption

- Idle: ~100 mA
- Active streaming: ~300-400 mA
- Peak (menu interaction): ~500 mA

Use quality USB-C cable and 5V/2A minimum power supply.

## Advanced Configuration

### Custom Build Flags

Edit `m5cardputer/platformio.ini`:

```ini
build_flags =
    -DCORE_DEBUG_LEVEL=2          # Increase debug verbosity
    -DBOARD_HAS_PSRAM=1           # PSRAM support
    -mfix-esp32-psram-cache-issue # Fix cache issues
    -O3                           # Optimization level
```

### Firmware Updates

To update firmware while preserving settings:

```bash
# Recompile with latest code
cd /home/user/KTOX_Pi/m5cardputer
git pull  # Get latest firmware

# Upload (settings preserved in SPIFFS)
platformio run -e m5stack-cardputer --target upload
```

### Debugging

Enable detailed logging:

Edit `m5cardputer/src/config.h`:

```cpp
#define DEBUG 1  // Enable debug output to serial

#if DEBUG
#define DEBUG_PRINTLN(x) Serial.println(x)
#define DEBUG_PRINT(x) Serial.print(x)
#define DEBUG_PRINTF(...) Serial.printf(__VA_ARGS__)
#else
// Disable to save memory
#endif
```

Monitor with:

```bash
platformio run -e m5stack-cardputer --target monitor --baud 115200
```

## Support Resources

- **M5Cardputer Build Guide**: See `m5cardputer/README.md`
- **Frame Capture Setup**: See `M5_CARDPUTER_SETUP.md`
- **Integration Verification**: See `M5_INTEGRATION_VERIFICATION.md`
- **Quick Start**: See `M5_QUICK_START.md`

## Common Questions

**Q: Can I use other ESP32 boards?**
A: Possibly, but you need to:
1. Have a 240x135 display
2. Update `platformio.ini` with your board config
3. Adjust pin definitions in M5Cardputer.ino

**Q: Is authentication required?**
A: No, but recommended. Set `RJ_WS_TOKEN` environment variable on KTOX_Pi if desired.

**Q: Can I run this on 5GHz WiFi?**
A: No, M5Cardputer only supports 2.4GHz WiFi (802.11b/g/n).

**Q: What if I lose the SSID/password?**
A: Settings are stored in SPIFFS. You can:
1. Reflash firmware (erases settings)
2. Or manually edit `/settings.json` if you can access SPIFFS

**Q: Can I control multiple KTOX_Pi devices?**
A: Not simultaneously, but you can reconfigure M5 via settings menu to switch hosts.

