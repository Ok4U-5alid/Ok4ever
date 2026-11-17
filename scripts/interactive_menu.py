#!/usr/bin/env python3
"""interactive_menu.py - Interactive Network Defense Menu (nftables edition)

Upgraded from iptables to nftables.
- Interactive terminal control for real-time traffic monitoring & blocking.
- Supports blocking and unblocking IPs and MACs via nftables.
- Displays live whitelisted IPv4, IPv6, and MAC addresses gathered from ARP/neighbor tables.
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
PACKET_LIMIT = 100
BAN_TIME = 60
STATIC_MACS = ["00:e0:4c:68:05:a0"]
STATIC_IPS = ["192.168.100.4"]
STATIC_MACS = ["ea:e2:5d:18:d3:94"]
STATIC_IPS = ["192.168.100.19"]
STATIC_MACS = ["42:30:fe:d6:a2:81"]
STATIC_IPS = ["192.168.100.101"]
STATIC_MACS = ["dc:03:98:98:8d:08"]
STATIC_IPS = ["192.168.100.91"]
# STATIC_MACS = [""]
# STATIC_IPS = ["192.168.100."]

blocked_ips = {}
packet_count = defaultdict(int)
monitoring_active = True

# ------------------------------------------------------------------
# Live Network & Whitelist Discovery
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
    try:
        res = subprocess.run(["ip", "neigh", "show"], capture_output=True, text=True, timeout=5)
        for line in res.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 5 and ":" in parts[4]:
                ips.add(parts[0])
                macs.add(parts[4].lower())
    except Exception:
        pass
    return iface, sorted(list(ips)), sorted(list(macs))

INTERFACE, WHITELISTED_IPS, WHITELISTED_MACS = get_live_network()

# ------------------------------------------------------------------
# nftables Operations
# ------------------------------------------------------------------
def init_nft():
    cmds = [
        "sudo nft add table inet firewall 2>/dev/null || true",
        "sudo nft add chain inet firewall input '{ type filter hook input priority 0; policy accept; }' 2>/dev/null || true",
        "sudo nft add set inet firewall blocked_ips '{ type ipv4_addr; flags interval; }' 2>/dev/null || true",
        "sudo nft add set inet firewall blocked_macs '{ type ether_addr; flags interval; }' 2>/dev/null || true",
        "sudo nft add rule inet firewall input ip saddr @blocked_ips drop 2>/dev/null || true",
        "sudo nft add rule inet firewall input ether saddr @blocked_macs drop 2>/dev/null || true",
    ]
    for cmd in cmds:
        os.system(cmd)

def block_ip(ip):
    if ip in WHITELISTED_IPS:
        print(f"[i] Refusing to block whitelisted IP: {ip}")
        return
    print(f"[!] Blocking IP (nftables): {ip}")
    os.system(f"sudo nft add element inet firewall blocked_ips {{ {ip} }} 2>/dev/null || true")
    blocked_ips[ip] = time.time()

def block_mac(mac):
    mac_clean = mac.lower().strip()
    if mac_clean in WHITELISTED_MACS:
        print(f"[i] Refusing to block whitelisted MAC: {mac_clean}")
        return
    print(f"[!] Blocking MAC (nftables): {mac_clean}")
    os.system(f"sudo nft add element inet firewall blocked_macs {{ {mac_clean} }} 2>/dev/null || true")

def unblock_ip(ip):
    print(f"[+] Unblocking IP (nftables): {ip}")
    os.system(f"sudo nft delete element inet firewall blocked_ips {{ {ip} }} 2>/dev/null || true")
    blocked_ips.pop(ip, None)

def unblock_mac(mac):
    mac_clean = mac.lower().strip()
    print(f"[+] Unblocking MAC (nftables): {mac_clean}")
    os.system(f"sudo nft delete element inet firewall blocked_macs {{ {mac_clean} }} 2>/dev/null || true")

def check_unblock():
    current_time = time.time()
    for ip in list(blocked_ips.keys()):
        if current_time - blocked_ips[ip] > BAN_TIME:
            unblock_ip(ip)

def process_packet(packet):
    if not monitoring_active:
        return
    if packet.haslayer(Ether):
        src_mac = packet[Ether].src.lower()
        if src_mac in WHITELISTED_MACS:
            return
    if packet.haslayer(IP):
        src_ip = packet[IP].src
        if src_ip in WHITELISTED_IPS:
            return
        packet_count[src_ip] += 1

def rate_limiter_loop():
    global packet_count
    while monitoring_active:
        time.sleep(1)
        for ip, count in list(packet_count.items()):
            if count > PACKET_LIMIT and ip not in blocked_ips:
                print(f"\n[!] High traffic detected from {ip} ({count} pkts/s) -> Blocking!")
                block_ip(ip)
        packet_count = defaultdict(int)
        check_unblock()

def show_status():
    print("\n--- nftables Blocked Sets ---")
    os.system("sudo nft list set inet firewall blocked_ips 2>/dev/null || echo 'No blocked_ips set'")
    os.system("sudo nft list set inet firewall blocked_macs 2>/dev/null || echo 'No blocked_macs set'")
    if blocked_ips:
        print("\nLocally Tracked Bans:")
        for ip, ts in blocked_ips.items():
            print(f"  {ip} (banned at {time.ctime(ts)})")
    else:
        print("\nNo active local timed bans.")

def show_whitelist():
    print(f"\n--- Live Whitelisted IPs ({len(WHITELISTED_IPS)}) ---")
    for ip in WHITELISTED_IPS:
        print(f"  {ip}")
    print(f"\n--- Live Whitelisted MACs ({len(WHITELISTED_MACS)}) ---")
    for mac in WHITELISTED_MACS:
        print(f"  {mac}")

def interactive_menu():
    global monitoring_active
    while True:
        print("\n" + "=" * 40)
        print("  Interactive Firewall Menu (nftables)")
        print("=" * 40)
        print(" 1. Show blocked IPs & MACs")
        print(" 2. Show live whitelisted IPs & MACs (ARP)")
        print(" 3. Manually block an IP")
        print(" 4. Manually block a MAC")
        print(" 5. Unblock an IP")
        print(" 6. Unblock a MAC")
        print(" 7. View full nftables ruleset")
        print(" 8. Flush all firewall rules")
        print(" 9. Exit")
        choice = input("Enter choice [1-9]: ").strip()

        if choice == "1":
            show_status()
        elif choice == "2":
            show_whitelist()
        elif choice == "3":
            ip = input("Enter IP to block: ").strip()
            if ip:
                block_ip(ip)
        elif choice == "4":
            mac = input("Enter MAC to block: ").strip()
            if mac:
                block_mac(mac)
        elif choice == "5":
            ip = input("Enter IP to unblock: ").strip()
            if ip:
                unblock_ip(ip)
        elif choice == "6":
            mac = input("Enter MAC to unblock: ").strip()
            if mac:
                unblock_mac(mac)
        elif choice == "7":
            os.system("sudo nft list ruleset")
        elif choice == "8":
            os.system("sudo nft flush ruleset")
            print("[+] Flushed nftables ruleset.")
        elif choice == "9":
            print("[*] Exiting firewall menu.")
            monitoring_active = False
            break
        else:
            print("[!] Invalid option, please try again.")

if __name__ == "__main__":
    init_nft()
    threading.Thread(target=rate_limiter_loop, daemon=True).start()
    threading.Thread(target=lambda: sniff(iface=INTERFACE, prn=process_packet, store=False), daemon=True).start()
    interactive_menu()
