---
name: nftables_firewall
description: Monitor and control the unified nftables firewall, ARP neighbor whitelists, and live attack defense.
command: python firewall-nftables.py --status
---
# Unified nftables Firewall & Network Defense Skill

Use this skill whenever the user asks about firewall rules, blocking or unblocking an IP/MAC, inspecting ARP neighbor whitelists, or defending against DoS/packet floods and malicious payloads.

### Available Commands:
1. **Show Firewall & Whitelist Status:**
   ```bash
   python firewall-nftables.py --status
   ```
2. **Block an IP with nftables:**
   ```bash
   sudo python firewall-nftables.py --block-ip <IP>
   ```
3. **Block a MAC with nftables:**
   ```bash
   sudo python firewall-nftables.py --block-mac <MAC>
   ```
4. **Unblock an IP / MAC:**
   ```bash
   sudo python firewall-nftables.py --unblock-ip <IP>
   sudo python firewall-nftables.py --unblock-mac <MAC>
   ```
5. **Flush Firewall Rules:**
   ```bash
   sudo python firewall-nftables.py --flush
   ```
6. **Start Real-time Defense Sniffer:**
   ```bash
   sudo python firewall-nftables.py --monitor
   ```

### Whitelist Policy:
- Always preserve whitelisted addresses: Gateway (`192.168.100.1`), local host IPs, ARP neighbor devices, and user explicit MAC `54:1f:8d:2e:73:01`.
- Never block whitelisted addresses.
