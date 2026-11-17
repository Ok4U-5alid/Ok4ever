#!/usr/bin/env python3
"""error.py - Network Traffic Inspector & Anti-DoS Firewall (nftables edition)

Upgraded from iptables/ufw to modern nftables.
- Auto-detects active interface (tfooo, eth0, wlan0).
- Dynamically loads ARP/Neighbor table to whitelist local IPv4, IPv6, and MAC addresses.
- Blocks IPs sending high packet rates or malicious payloads (.exe, .bat) using nftables.
- Automatically unblocks after BAN_TIME.
"""

from scapy.all import sniff, TCP, IP, Ether, wrpcap
import os
import subprocess
import time
import socket
import re
import threading
from collections import defaultdict

# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------
PACKET_LIMIT = 20         # Max packets per IP per second
BAN_TIME = 60             # Ban duration in seconds
BLOCKED_EXTENSIONS = ['.exe', '.bat', '.cmd', '.ps1']

# User explicit whitelists (merged with live ARP/Neighbor discovery)
STATIC_WHITELISTED_MACS = ['f8:9a:25:d0:97:90']
STATIC_WHITELISTED_IPS = ['192.168.100.1']
# STATIC_WHITELISTED_DOMAINS = ['ok.com']

packet_count = defaultdict(int)
blocked_ips = {}
captured_packets = []

# ------------------------------------------------------------------
# Dynamic Network Discovery & Whitelisting
# ------------------------------------------------------------------
def get_live_network_info():
    """Extract default interface, host IPs, gateway, and live ARP/neighbor entries."""
    ips = set(["127.0.0.1", "::1"])
    ips.update(STATIC_WHITELISTED_IPS)
    macs = set(m.lower().strip() for m in STATIC_WHITELISTED_MACS)
    default_iface = "eth0"

    # 1. Default route & interface
    try:
        res = subprocess.run(["ip", "route", "show", "default"], capture_output=True, text=True, timeout=5)
        m = re.search(r"default via (\S+) dev (\S+)", res.stdout)
        if m:
            ips.add(m.group(1))
            default_iface = m.group(2)
    except Exception:
        pass

    # 2. Host addresses
    try:
        res = subprocess.run(["ip", "addr", "show"], capture_output=True, text=True, timeout=5)
        for line in res.stdout.splitlines():
            m_ip4 = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", line)
            if m_ip4:
                ips.add(m_ip4.group(1))
            m_ip6 = re.search(r"inet6 ([a-fA-F0-9:]+)/", line)
            if m_ip6:
                ips.add(m_ip6.group(1))
            m_mac = re.search(r"link/ether ([0-9a-fA-F:]{17})", line)
            if m_mac:
                macs.add(m_mac.group(1).lower())
    except Exception:
        pass

    # 3. ARP table
    try:
        res = subprocess.run(["arp", "-a"], capture_output=True, text=True, timeout=5)
        for line in res.stdout.splitlines():
            m = re.search(r"\(([\d\.]+)\) at ([0-9a-fA-F:]{17})", line)
            if m:
                ips.add(m.group(1))
                macs.add(m.group(2).lower())
    except Exception:
        pass

    # 4. IPv6 and IPv4 Neighbor table
    try:
        res = subprocess.run(["ip", "neigh", "show"], capture_output=True, text=True, timeout=5)
        for line in res.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 5 and ":" in parts[4]:
                ips.add(parts[0])
                macs.add(parts[4].lower())
    except Exception:
        pass

    return default_iface, sorted(list(ips)), sorted(list(macs))

INTERFACE, WHITELISTED_IPS, WHITELISTED_MACS = get_live_network_info()

# ------------------------------------------------------------------
# nftables Integration
# ------------------------------------------------------------------
def init_nft():
    """Ensure the inet firewall table and blocked_ips set exist."""
    cmds = [
        "sudo nft add table inet firewall 2>/dev/null || true",
        "sudo nft add chain inet firewall input '{ type filter hook input priority 0; policy accept; }' 2>/dev/null || true",
        "sudo nft add set inet firewall blocked_ips '{ type ipv4_addr; flags interval; }' 2>/dev/null || true",
        "sudo nft add rule inet firewall input ip saddr @blocked_ips drop 2>/dev/null || true",
    ]
    for cmd in cmds:
        os.system(cmd)

def block_ip(ip):
    """Block an IP using nftables (respecting whitelist)."""
    if ip in WHITELISTED_IPS:
        print(f"[i] Whitelisted IP ignored from block: {ip}")
        return

    print(f"[!] Blocking IP with nftables: {ip}")
    os.system(f"sudo nft add element inet firewall blocked_ips {{ {ip} }} 2>/dev/null || true")
    blocked_ips[ip] = time.time()

def check_unblock():
    """Unblock expired IPs from nftables."""
    current_time = time.time()
    for ip in list(blocked_ips.keys()):
        if current_time - blocked_ips[ip] > BAN_TIME:
            print(f"[+] Unblocking IP from nftables: {ip}")
            os.system(f"sudo nft delete element inet firewall blocked_ips {{ {ip} }} 2>/dev/null || true")
            del blocked_ips[ip]

def is_blocked_extension(data):
    """Check if raw packet data contains forbidden file extensions."""
    for ext in BLOCKED_EXTENSIONS:
        if ext in data:
            return True
    return False

def process_packet(packet):
    """Process each packet received."""
    if packet.haslayer(Ether):
        src_mac = packet[Ether].src.lower()
        if src_mac in WHITELISTED_MACS:
            return  # Allow whitelisted MAC

    if packet.haslayer("IP") and packet.haslayer(TCP):
        src_ip = packet["IP"].src
        if src_ip in WHITELISTED_IPS:
            return  # Allow whitelisted IP

        if packet.haslayer("Raw"):
            payload = str(packet["Raw"].load)
            if is_blocked_extension(payload):
                print(f"[!] Blocked packet from {src_ip} containing forbidden extension.")
                block_ip(src_ip)
                captured_packets.append(packet)
                return

        packet_count[src_ip] = packet_count.get(src_ip, 0) + 1

def reset_count():
    """Rate limit evaluator running every second."""
    global packet_count
    while True:
        time.sleep(1)
        for ip, count in list(packet_count.items()):
            if count > PACKET_LIMIT and ip not in blocked_ips:
                print(f"[!] Rate limit exceeded by {ip} ({count} pkts/s) -> Blocking!")
                block_ip(ip)
        packet_count = defaultdict(int)
        check_unblock()

def save_captured_packets():
    """Save suspicious captured packets to a PCAP file."""
    if captured_packets:
        wrpcap("captured_packets.pcap", captured_packets)
        print(f"[*] Saved {len(captured_packets)} captured packets to 'captured_packets.pcap'.")

if __name__ == "__main__":
    init_nft()
    print("=" * 60)
    print("  error.py - Traffic Inspector (nftables)")
    print(f"  Active Interface : {INTERFACE}")
    print(f"  Whitelisted IPs  : {len(WHITELISTED_IPS)} (Gateway, Hosts, ARP peers)")
    print(f"  Whitelisted MACs : {len(WHITELISTED_MACS)} (Includes 54:1f:8d:2e:73:01)")
    print("=" * 60)

    threading.Thread(target=reset_count, daemon=True).start()
    print(f"[*] Monitoring traffic on {INTERFACE} (Press Ctrl+C to stop)...")
    try:
        sniff(iface=INTERFACE, prn=process_packet, store=False)
    except KeyboardInterrupt:
        print("\n[*] Stopping monitor.")
        save_captured_packets()
