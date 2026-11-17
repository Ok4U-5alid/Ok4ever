#!/usr/bin/env python3
"""packet.py - Anti-DoS Rate Limiter & Packet Monitor (nftables edition)

Upgraded from iptables to nftables.
- Automatically detects active network interface.
- Dynamically discovers and whitelists local IPs, gateway, and ARP peers.
- Drops IPs exceeding PACKET_LIMIT using nftables sets with auto-expiry.
"""

from scapy.all import sniff, IP, Ether
import os
import subprocess
import time
import re
import threading
from collections import defaultdict

# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------
PACKET_LIMIT = 100       # Max packets per IP per second
BAN_TIME = 60            # Ban time in seconds
STATIC_MACS = ["54:1f:8d:2e:73:01"]
STATIC_IPS = ["192.168.0.14"]

blocked_ips = {}
packet_count = defaultdict(int)

# ------------------------------------------------------------------
# Dynamic Network & Whitelist Discovery
# ------------------------------------------------------------------
def get_live_network():
    ips = set(["127.0.0.1", "::1"])
    ips.update(STATIC_IPS)
    macs = set(m.lower().strip() for m in STATIC_MACS)
    iface = "eth0"

    try:
        res = subprocess.run(["ip", "route", "show", "default"], capture_output=True, text=True, timeout=5)
        m = re.search(r"default via (\S+) dev (\S+)", res.stdout)
        if m:
            ips.add(m.group(1))
            iface = m.group(2)
    except Exception:
        pass

    try:
        res = subprocess.run(["arp", "-a"], capture_output=True, text=True, timeout=5)
        for line in res.stdout.splitlines():
            m = re.search(r"\(([\d\.]+)\) at ([0-9a-fA-F:]{17})", line)
            if m:
                ips.add(m.group(1))
                macs.add(m.group(2).lower())
    except Exception:
        pass

    try:
        res = subprocess.run(["ip", "addr", "show"], capture_output=True, text=True, timeout=5)
        for line in res.stdout.splitlines():
            m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", line)
            if m:
                ips.add(m.group(1))
            m_mac = re.search(r"link/ether ([0-9a-fA-F:]{17})", line)
            if m_mac:
                macs.add(m_mac.group(1).lower())
    except Exception:
        pass

    return iface, sorted(list(ips)), sorted(list(macs))

INTERFACE, WHITELISTED_IPS, WHITELISTED_MACS = get_live_network()

# ------------------------------------------------------------------
# nftables Handlers
# ------------------------------------------------------------------
def init_nft():
    cmds = [
        "sudo nft add table inet firewall 2>/dev/null || true",
        "sudo nft add chain inet firewall input '{ type filter hook input priority 0; policy accept; }' 2>/dev/null || true",
        "sudo nft add set inet firewall blocked_ips '{ type ipv4_addr; flags interval; }' 2>/dev/null || true",
        "sudo nft add rule inet firewall input ip saddr @blocked_ips drop 2>/dev/null || true",
    ]
    for cmd in cmds:
        os.system(cmd)

def block_ip(ip):
    if ip in WHITELISTED_IPS:
        print(f"[i] Whitelisted IP spared from block: {ip}")
        return
    print(f"[!] Blocking IP via nftables: {ip}")
    os.system(f"sudo nft add element inet firewall blocked_ips {{ {ip} }} 2>/dev/null || true")
    blocked_ips[ip] = time.time()

def check_unblock():
    current_time = time.time()
    for ip in list(blocked_ips.keys()):
        if current_time - blocked_ips[ip] > BAN_TIME:
            print(f"[+] Unblocking IP via nftables: {ip}")
            os.system(f"sudo nft delete element inet firewall blocked_ips {{ {ip} }} 2>/dev/null || true")
            del blocked_ips[ip]

def process_packet(packet):
    if packet.haslayer(Ether):
        src_mac = packet[Ether].src.lower()
        if src_mac in WHITELISTED_MACS:
            return

    if packet.haslayer(IP):
        src_ip = packet[IP].src
        if src_ip in WHITELISTED_IPS:
            return
        packet_count[src_ip] += 1

def reset_count():
    global packet_count
    while True:
        time.sleep(1)
        for ip, count in list(packet_count.items()):
            if count > PACKET_LIMIT and ip not in blocked_ips:
                print(f"[!] Flood detected from {ip} ({count} pkts/s) -> Blocking!")
                block_ip(ip)
        packet_count = defaultdict(int)
        check_unblock()

if __name__ == "__main__":
    init_nft()
    print("=" * 60)
    print("  packet.py - Anti-DoS Rate Limiter (nftables)")
    print(f"  Interface       : {INTERFACE}")
    print(f"  Whitelisted IPs : {len(WHITELISTED_IPS)}")
    print(f"  Whitelisted MACs: {len(WHITELISTED_MACS)} (Includes 54:1f:8d:2e:73:01)")
    print("=" * 60)

    threading.Thread(target=reset_count, daemon=True).start()
    print(f"[*] Monitoring traffic on {INTERFACE}...")
    try:
        sniff(iface=INTERFACE, prn=process_packet, store=False)
    except KeyboardInterrupt:
        print("\n[*] Stopped.")


def process(text: str) -> str:
    """Module pre-processor for ai_server."""
    return text
