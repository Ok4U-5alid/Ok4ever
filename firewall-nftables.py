#!/usr/bin/env python3
"""firewall-nftables.py - Unified All-in-One Network Defense & Firewall System

Consolidates all scripts into a single unified Python firewall:
1. nftables engine: High-performance set-based blocking (replaces iptables and ufw).
2. Dynamic Whitelist: Auto-discovers gateway, host IPv4/IPv6, and ARP neighbors from `$arp -a` and `ip neigh`.
3. Explicit Whitelists: Includes user MAC '00:e0:4c:68:05:a0', local subnets, and trusted domains.
4. Rate-Limiting & DoS Defense: Blocks aggressive packet floods per IP.
5. Payload Inspection: Drops and bans packets carrying forbidden executable extensions (.exe, .bat).
6. Tear Drop / Fragment Defense: Detects and drops illegal IP fragmentation offsets.
7. Multi-Mode CLI: Interactive Menu, Background Monitor, Status Check, and Fast CLI Banning.

Usage:
    sudo python firewall-nftables.py               # Launches interactive menu
    sudo python firewall-nftables.py --monitor     # Starts live packet inspection & auto-defense
    python firewall-nftables.py --status           # Shows active nftables rules and ARP whitelist
    sudo python firewall-nftables.py --block-ip 1.2.3.4
    sudo python firewall-nftables.py --unblock-ip 1.2.3.4
    sudo python firewall-nftables.py --flush
"""

import argparse
import os
import re
import socket
import subprocess
import sys
import threading
import time
from collections import defaultdict

# ------------------------------------------------------------------
# Scapy conditional import
# ------------------------------------------------------------------
try:
    from scapy.all import sniff, IP, IPv6, TCP, UDP, Ether, ARP, wrpcap
    SCAPY_AVAILABLE = True
except ImportError:
    SCAPY_AVAILABLE = False

# ------------------------------------------------------------------
# Configuration Defaults
# ------------------------------------------------------------------
PACKET_LIMIT = 50           # Max packets per IP per second before auto-ban
BAN_TIME = 60               # Ban duration in seconds
BLOCKED_EXTENSIONS = ['.exe', '.bat', '.cmd', '.ps1', '.vbs']
STATIC_WHITELISTED_MACS = ['00:e0:4c:68:05:a0']
STATIC_WHITELISTED_IPS = ['192.168.1000.4']
STATIC_WHITELISTED_MACS = ['ea:e2:5d:18:d3:94']
STATIC_WHITELISTED_IPS = ['192.168.100.19']
STATIC_WHITELISTED_MACS = ['42:30:fe:d6:a2:81']
STATIC_WHITELISTED_IPS = ['192.168.100.101']
# STATIC_WHITELISTED_MACS = ['dc:03:98:98:8d:08']
# STATIC_WHITELISTED_IPS = ['192.168.100.91']
# STATIC_WHITELISTED_MACS = ['']
# STATIC_WHITELISTED_IPS = ['']

STATIC_WHITELISTED_DOMAINS = ['ok.com']

# In-memory tracking
packet_counts = defaultdict(int)
active_bans = {}            # ip -> ban_timestamp
captured_attacks = []
running_flag = True

# ------------------------------------------------------------------
# Live Network & ARP / Neighbor Discovery
# ------------------------------------------------------------------
def get_live_network_info():
    """Dynamically extract interface, gateway, host IPs, and ARP neighbor table."""
    ips = set(["127.0.0.1", "::1"])
    ips.update(STATIC_WHITELISTED_IPS)
    macs = set(m.lower().strip() for m in STATIC_WHITELISTED_MACS)
    default_iface = "eth0"
    gateway_ip = None

    # 1. Default route & active interface
    try:
        res = subprocess.run(["ip", "route", "show", "default"], capture_output=True, text=True, timeout=5)
        m = re.search(r"default via (\S+) dev (\S+)", res.stdout)
        if m:
            gateway_ip = m.group(1)
            default_iface = m.group(2)
            ips.add(gateway_ip)
    except Exception:
        pass

    # 2. Local Host addresses (IPv4 & IPv6)
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

    # 3. ARP table (`arp -a`)
    try:
        res = subprocess.run(["arp", "-a"], capture_output=True, text=True, timeout=5)
        for line in res.stdout.splitlines():
            m = re.search(r"\(([\d\.]+)\) at ([0-9a-fA-F:]{17})", line)
            if m:
                ips.add(m.group(1))
                macs.add(m.group(2).lower())
    except Exception:
        pass

    # 4. IPv6 and IPv4 Neighbor cache (`ip neigh`)
    try:
        res = subprocess.run(["ip", "neigh", "show"], capture_output=True, text=True, timeout=5)
        for line in res.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 5 and ":" in parts[4]:
                ips.add(parts[0])
                macs.add(parts[4].lower())
    except Exception:
        pass

    return {
        "interface": default_iface,
        "gateway": gateway_ip,
        "whitelisted_ips": sorted(list(ips)),
        "whitelisted_macs": sorted(list(macs)),
    }

# ------------------------------------------------------------------
# nftables Engine
# ------------------------------------------------------------------
def run_cmd(cmd: str, check: bool = False) -> str:
    try:
        # Use sudo -n to avoid hanging on password prompts when non-root
        safe_cmd = cmd.replace("sudo ", "sudo -n ") if "sudo " in cmd else cmd
        res = subprocess.run(safe_cmd, shell=True, capture_output=True, text=True, timeout=10)
        return res.stdout.strip()
    except Exception as e:
        return ""

def init_firewall():
    """Initialize table, chains, and sets in nftables."""
    cmds = [
        "sudo nft add table inet firewall 2>/dev/null || true",
        "sudo nft add chain inet firewall input '{ type filter hook input priority 0; policy accept; }' 2>/dev/null || true",
        "sudo nft add chain inet firewall forward '{ type filter hook forward priority 0; policy accept; }' 2>/dev/null || true",
        "sudo nft add chain inet firewall output '{ type filter hook output priority 0; policy accept; }' 2>/dev/null || true",
        "sudo nft add set inet firewall blocked_ips '{ type ipv4_addr; flags interval; }' 2>/dev/null || true",
        "sudo nft add set inet firewall blocked_macs '{ type ether_addr; flags interval; }' 2>/dev/null || true",
        "sudo nft add rule inet firewall input ip saddr @blocked_ips drop 2>/dev/null || true",
        "sudo nft add rule inet firewall forward ip saddr @blocked_ips drop 2>/dev/null || true",
        "sudo nft add rule inet firewall input ether saddr @blocked_macs drop 2>/dev/null || true",
        "sudo nft add rule inet firewall forward ether saddr @blocked_macs drop 2>/dev/null || true",
    ]
    for c in cmds:
        run_cmd(c)

def block_ip(ip: str, net_info: dict | None = None):
    net_info = net_info or get_live_network_info()
    if ip in net_info["whitelisted_ips"]:
        print(f"[i] Refusing to block whitelisted IP: {ip}")
        return False
    print(f"[!] [nftables] Adding DROP rule for IP: {ip}")
    run_cmd(f"sudo nft add element inet firewall blocked_ips {{ {ip} }} 2>/dev/null || true")
    active_bans[ip] = time.time()
    return True

def block_mac(mac: str, net_info: dict | None = None):
    net_info = net_info or get_live_network_info()
    mac_clean = mac.lower().strip()
    if mac_clean in net_info["whitelisted_macs"]:
        print(f"[i] Refusing to block whitelisted MAC: {mac_clean}")
        return False
    print(f"[!] [nftables] Adding DROP rule for MAC: {mac_clean}")
    run_cmd(f"sudo nft add element inet firewall blocked_macs {{ {mac_clean} }} 2>/dev/null || true")
    return True

def unblock_ip(ip: str):
    print(f"[+] [nftables] Removing DROP rule for IP: {ip}")
    run_cmd(f"sudo nft delete element inet firewall blocked_ips {{ {ip} }} 2>/dev/null || true")
    active_bans.pop(ip, None)

def unblock_mac(mac: str):
    mac_clean = mac.lower().strip()
    print(f"[+] [nftables] Removing DROP rule for MAC: {mac_clean}")
    run_cmd(f"sudo nft delete element inet firewall blocked_macs {{ {mac_clean} }} 2>/dev/null || true")

def flush_firewall():
    print("[*] Flushing entire nftables firewall ruleset...")
    run_cmd("sudo nft flush ruleset")
    active_bans.clear()
    print("[+] Firewall flushed.")

def check_auto_unblock():
    """Unblock expired timed bans."""
    now = time.time()
    for ip in list(active_bans.keys()):
        if now - active_bans[ip] > BAN_TIME:
            print(f"[+] Ban expired ({BAN_TIME}s). Unblocking {ip}...")
            unblock_ip(ip)

# ------------------------------------------------------------------
# Traffic Sniffer & Attack Detection
# ------------------------------------------------------------------
def is_malicious_payload(data: str) -> bool:
    for ext in BLOCKED_EXTENSIONS:
        if ext in data:
            return True
    return False

def packet_callback(pkt, net_info: dict):
    if not running_flag:
        return

    # Check MAC Whitelist
    if Ether in pkt:
        src_mac = pkt[Ether].src.lower()
        if src_mac in net_info["whitelisted_macs"]:
            return

    # IPv4 Inspection
    if IP in pkt:
        src_ip = pkt[IP].src
        if src_ip in net_info["whitelisted_ips"]:
            return

        # 1. Tear Drop / Fragment offset detection
        frag_offset = pkt[IP].frag
        if frag_offset > 0 and (frag_offset % 8 != 0 or frag_offset > 8192):
            print(f"[!] Attack detected: Illegal Fragmentation (Tear Drop) from {src_ip} (offset: {frag_offset})")
            block_ip(src_ip, net_info)
            captured_attacks.append(pkt)
            return

        # 2. Payload Inspection (.exe / .bat)
        if TCP in pkt and pkt.haslayer("Raw"):
            try:
                payload = str(pkt["Raw"].load)
                if is_malicious_payload(payload):
                    print(f"[!] Attack detected: Forbidden file payload from {src_ip}")
                    block_ip(src_ip, net_info)
                    captured_attacks.append(pkt)
                    return
            except Exception:
                pass

        # 3. Rate limiting count
        packet_counts[src_ip] += 1

def rate_limiter_daemon(net_info: dict):
    global packet_counts
    while running_flag:
        time.sleep(1)
        for ip, count in list(packet_counts.items()):
            if count > PACKET_LIMIT and ip not in active_bans:
                print(f"[!] Rate limit exceeded: {ip} sent {count} pkts/s -> Auto-Banning!")
                block_ip(ip, net_info)
        packet_counts = defaultdict(int)
        check_auto_unblock()

def start_monitor_mode(interface: str | None = None):
    if not SCAPY_AVAILABLE:
        print("[!] Error: scapy is required for monitor mode. Run: pip install scapy")
        return

    init_firewall()
    net = get_live_network_info()
    iface = interface or net["interface"]

    print("=" * 65)
    print("  firewall-nftables.py - Real-Time Autonomous Network Defense")
    print(f"  Active Interface    : {iface}")
    print(f"  Gateway IP          : {net['gateway']}")
    print(f"  Whitelisted IPs     : {len(net['whitelisted_ips'])} (Host, Gateway, Neighbors)")
    print(f"  Whitelisted MACs    : {len(net['whitelisted_macs'])} (Includes 54:1f:8d:2e:73:01)")
    print(f"  Rate Limit Threshold: {PACKET_LIMIT} pkts/sec | Ban Time: {BAN_TIME}s")
    print("=" * 65)

    threading.Thread(target=rate_limiter_daemon, args=(net,), daemon=True).start()
    print(f"[*] Sniffing & Defending on {iface}... (Press Ctrl+C to stop)\n")

    try:
        sniff(iface=iface, prn=lambda p: packet_callback(p, net), store=False)
    except KeyboardInterrupt:
        print("\n[*] Stopping monitor.")
        if captured_attacks:
            wrpcap("attacks_captured.pcap", captured_attacks)
            print(f"[*] Saved {len(captured_attacks)} attack packets to 'attacks_captured.pcap'.")

# ------------------------------------------------------------------
# Status & Reports
# ------------------------------------------------------------------
def print_status():
    net = get_live_network_info()
    print("=" * 65)
    print("  NFTABLES FIREWALL STATUS & ARP DISCOVERY")
    print("=" * 65)
    print(f"Default Interface : {net['interface']}")
    print(f"Gateway Address   : {net['gateway'] or 'None detected'}")
    print(f"Active Local Bans : {len(active_bans)}")

    print(f"\n--- Whitelisted IPs ({len(net['whitelisted_ips'])}) ---")
    for ip in net['whitelisted_ips']:
        print(f"  [+] {ip}")

    print(f"\n--- Whitelisted MACs ({len(net['whitelisted_macs'])}) ---")
    for mac in net['whitelisted_macs']:
        label = " (User Whitelist)" if mac == "54:1f:8d:2e:73:01" else ""
        print(f"  [+] {mac}{label}")

    print("\n--- nftables Blocked Sets ---")
    blocked_ips_out = run_cmd("sudo nft list set inet firewall blocked_ips 2>/dev/null")
    blocked_macs_out = run_cmd("sudo nft list set inet firewall blocked_macs 2>/dev/null")
    print(blocked_ips_out or "  Set 'blocked_ips' is empty or not initialized.")
    print(blocked_macs_out or "  Set 'blocked_macs' is empty or not initialized.")

    print("\n--- Active Chains in Table 'firewall' ---")
    rules = run_cmd("sudo nft list table inet firewall 2>/dev/null")
    print(rules or "  Table inet firewall does not exist yet. Run with --monitor or --menu to init.")
    print("=" * 65)

# ------------------------------------------------------------------
# Interactive CLI Menu
# ------------------------------------------------------------------
def interactive_menu():
    global running_flag
    init_firewall()
    net = get_live_network_info()

    # Start background rate limiter & unblock daemon
    threading.Thread(target=rate_limiter_daemon, args=(net,), daemon=True).start()

    while True:
        print("\n" + "=" * 50)
        print("   NFTABLES FIREWALL INTERACTIVE CONTROL MENU")
        print("=" * 50)
        print(" 1. Show firewall rules & blocked sets")
        print(" 2. Show live ARP & IPv6 neighbor whitelist")
        print(" 3. Manually block an IP address")
        print(" 4. Manually block a MAC address")
        print(" 5. Unblock an IP address")
        print(" 6. Unblock a MAC address")
        print(" 7. Refresh live ARP/Neighbor whitelist")
        print(" 8. Enable anti-spoofing (rpfilter rule)")
        print(" 9. Flush all firewall rules")
        print(" 10. Start packet sniffer & attack monitor")
        print(" 11. Exit")
        print("=" * 50)
        choice = input("Select an option [1-11]: ").strip()

        if choice == "1":
            print_status()
        elif choice == "2":
            net = get_live_network_info()
            print(f"\n--- Live IPs ({len(net['whitelisted_ips'])}) ---")
            for ip in net['whitelisted_ips']:
                print(f"  IP: {ip}")
            print(f"\n--- Live MACs ({len(net['whitelisted_macs'])}) ---")
            for mac in net['whitelisted_macs']:
                print(f"  MAC: {mac}")
        elif choice == "3":
            target_ip = input("Enter IPv4 address to block: ").strip()
            if target_ip:
                block_ip(target_ip, net)
        elif choice == "4":
            target_mac = input("Enter MAC address to block: ").strip()
            if target_mac:
                block_mac(target_mac, net)
        elif choice == "5":
            target_ip = input("Enter IPv4 address to unblock: ").strip()
            if target_ip:
                unblock_ip(target_ip)
        elif choice == "6":
            target_mac = input("Enter MAC address to unblock: ").strip()
            if target_mac:
                unblock_mac(target_mac)
        elif choice == "7":
            net = get_live_network_info()
            print(f"[+] Refreshed: {len(net['whitelisted_ips'])} IPs, {len(net['whitelisted_macs'])} MACs.")
        elif choice == "8":
            run_cmd("sudo nft add rule inet firewall input fib saddr != oif drop 2>/dev/null || true")
            print("[+] Anti-spoofing protection enabled via nftables rpfilter.")
        elif choice == "9":
            confirm = input("Are you sure you want to flush all rules? (y/n): ").strip().lower()
            if confirm == "y":
                flush_firewall()
        elif choice == "10":
            start_monitor_mode(net["interface"])
        elif choice == "11":
            print("[*] Exiting firewall control.")
            running_flag = False
            break
        else:
            print("[!] Invalid selection, please choose [1-11].")

# ------------------------------------------------------------------
# Main Entry Point
# ------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Unified nftables Network Firewall & Defense System")
    parser.add_argument("--monitor", action="store_true", help="start real-time packet inspection and attack defense")
    parser.add_argument("--status", action="store_true", help="show active nftables rules and ARP discovery status")
    parser.add_argument("--block-ip", metavar="IP", help="manually block an IP via nftables")
    parser.add_argument("--block-mac", metavar="MAC", help="manually block a MAC via nftables")
    parser.add_argument("--unblock-ip", metavar="IP", help="manually unblock an IP via nftables")
    parser.add_argument("--unblock-mac", metavar="MAC", help="manually unblock a MAC via nftables")
    parser.add_argument("--flush", action="store_true", help="flush nftables firewall rules")
    parser.add_argument("-i", "--interface", help="override network interface (default: auto-detected)")
    args = parser.parse_args()

    if args.status:
        print_status()
        return

    if args.flush:
        flush_firewall()
        return

    if args.block_ip:
        init_firewall()
        block_ip(args.block_ip)
        return

    if args.block_mac:
        init_firewall()
        block_mac(args.block_mac)
        return

    if args.unblock_ip:
        unblock_ip(args.unblock_ip)
        return

    if args.unblock_mac:
        unblock_mac(args.unblock_mac)
        return

    if args.monitor:
        start_monitor_mode(args.interface)
        return

    # Default: Interactive Menu
    interactive_menu()

if __name__ == "__main__":
    main()
