#!/usr/bin/env python3
"""route.py - Tear Drop & Fragment Attack Defender (nftables edition)

Upgraded from iptables to nftables.
- Defends against illegal packet fragmentation (e.g. Tear Drop attacks).
- Automatically detects active network interface.
- Respects dynamic ARP/IP/MAC whitelist (prevents blocking gateway & trusted nodes).
"""

from scapy.all import sniff, IP, Ether
import os
import subprocess
import time
import re
from collections import defaultdict

MAX_PACKETS = 100
TIME_WINDOW = 1
packet_count = defaultdict(list)
STATIC_MACS = ["54:1f:8d:2e:73:01"]

def get_live_network():
    ips = set(["127.0.0.1", "::1"])
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

def init_nft():
    cmds = [
        "sudo nft add table inet firewall 2>/dev/null || true",
        "sudo nft add chain inet firewall forward '{ type filter hook forward priority 0; policy accept; }' 2>/dev/null || true",
        "sudo nft add chain inet firewall input '{ type filter hook input priority 0; policy accept; }' 2>/dev/null || true",
        "sudo nft add set inet firewall blocked_ips '{ type ipv4_addr; flags interval; }' 2>/dev/null || true",
        "sudo nft add rule inet firewall forward ip saddr @blocked_ips drop 2>/dev/null || true",
        "sudo nft add rule inet firewall input ip saddr @blocked_ips drop 2>/dev/null || true",
    ]
    for cmd in cmds:
        os.system(cmd)

def enable_promiscuous(interface):
    os.system(f"sudo ip link set {interface} promisc on 2>/dev/null || true")
    print(f"[*] Promiscuous Mode enabled on {interface}")

def block_ip(ip):
    if ip in WHITELISTED_IPS:
        print(f"[i] Whitelisted IP ignored from block: {ip}")
        return
    print(f"[!] Blocking IP across forward & input via nftables: {ip}")
    os.system(f"sudo nft add element inet firewall blocked_ips {{ {ip} }} 2>/dev/null || true")

def process_packet(packet):
    if packet.haslayer(Ether):
        src_mac = packet[Ether].src.lower()
        if src_mac in WHITELISTED_MACS:
            return

    if packet.haslayer(IP):
        src_ip = packet[IP].src
        if src_ip in WHITELISTED_IPS:
            return

        frag_offset = packet[IP].frag
        # Detect malicious fragmented attacks (e.g. Tear Drop)
        if frag_offset > 0 and (frag_offset % 8 != 0 or frag_offset > 8192):
            print(f"[!] Tear Drop Attack detected from {src_ip} (Frag offset: {frag_offset}) -> Blocking!")
            block_ip(src_ip)
            return

        current_time = time.time()
        packet_count[src_ip].append(current_time)
        packet_count[src_ip] = [t for t in packet_count[src_ip] if current_time - t < TIME_WINDOW]

        if len(packet_count[src_ip]) > MAX_PACKETS:
            print(f"[!] DoS Flood detected from {src_ip} -> Blocking!")
            block_ip(src_ip)

if __name__ == "__main__":
    init_nft()
    enable_promiscuous(INTERFACE)
    print("=" * 60)
    print("  route.py - Tear Drop & Fragment Defender (nftables)")
    print(f"  Interface       : {INTERFACE}")
    print(f"  Whitelisted IPs : {len(WHITELISTED_IPS)}")
    print(f"  Whitelisted MACs: {len(WHITELISTED_MACS)} (Includes 54:1f:8d:2e:73:01)")
    print("=" * 60)

    print(f"[*] Monitoring network traffic on {INTERFACE}...")
    try:
        sniff(filter="ip", iface=INTERFACE, prn=process_packet, store=0)
    except KeyboardInterrupt:
        print("\n[*] Stopped.")


def process(text: str) -> str:
    """Module pre-processor for ai_server."""
    return text
