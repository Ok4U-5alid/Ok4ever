# Migration & Unified Firewall Plan (iptables/ufw -> nftables)

## 1. Overview
All legacy `iptables` and `ufw` firewall calls across the network defense scripts have been upgraded to modern Linux `nftables` (`table inet firewall`). 

The hardcoded old IP `192.168.0.14` has been replaced with **Dynamic Network & ARP Discovery**, which automatically parses live entries from:
- `arp -a`
- `ip neigh show` (IPv4 and IPv6 neighbors)
- `ip addr show` (Local host IP and IPv6 addresses)
- `ip route show default` (Gateway IP and active default interface)
- User explicit whitelist: MAC `54:1f:8d:2e:73:01`

---

## 2. Dynamic Whitelist Details (Auto-detected from Live System)

### Whitelisted IPv4 Addresses:
- Gateway: `192.168.100.1`
- Local Host: `192.168.100.4`, `192.168.100.104`, `127.0.0.1`
- Live ARP Neighbors: `192.168.100.19`, `192.168.100.91`, `192.168.100.101`
- Static Fallback: `192.168.0.14`

### Whitelisted IPv6 Addresses:
- `::1` (Loopback)
- `fe80::1` (Default IPv6 Gateway router)
- `fe80::fa9a:25ff:fed0:9790` (IPv6 Neighbor)
- `2001:16a2:335a:6a00:3cc0:666e:57bb:a599` (Global dynamic address)
- `fe80::2187:5b20:44d8:af13` (Link-local host)

### Whitelisted MAC Addresses:
- User Explicit Whitelist: `54:1f:8d:2e:73:01`
- Local Interface (`tfooo`): `00:e0:4c:68:05:a0`
- Gateway Router: `f8:9a:25:d0:97:90`
- Wireless Interface: `f2:6f:4a:8c:6b:2d`
- ARP Neighbors: `ea:e2:5d:18:d3:94`, `dc:03:98:98:8d:08`, `42:30:fe:d6:a2:81`

---

## 3. Updated Scripts in `scripts/`

1. **[`error.py`](error.py)**:
   - Upgraded from `iptables -A INPUT` to `nftables` sets (`inet firewall blocked_ips`).
   - Dynamic interface detection (detects active interface `tfooo`).
   - Blocks packets carrying malicious payload extensions (`.exe`, `.bat`, `.cmd`, `.ps1`).
   - Protects all whitelisted IPs and MACs from being blocked.

2. **[`packet.py`](packet.py)**:
   - Replaced `iptables` with `nftables`.
   - Rate-limits packets per second per IP (`PACKET_LIMIT = 100`).
   - Automatically unblocks after `BAN_TIME = 60s`.

3. **[`route.py`](route.py) & [`router.py`](router.py)**:
   - Defends against illegal fragmentation (Tear Drop attacks).
   - Replaced `iptables -A FORWARD` with `nftables forward` chain filtering.
   - Enables promiscuous mode on active interface and inspects transit traffic.

4. **[`interactive_menu.py`](interactive_menu.py)**:
   - Terminal interactive menu with options to show rules, block/unblock IPs and MACs, and inspect live ARP whitelists.

5. **[`snifF.py`](snifF.py)**:
   - Scapy sniffer updated with automatic default interface detection.

---

## 4. The Master Script: `firewall-nftables.py`

Located at:
- [`/var/www/html/python/mystatic/firewall-nftables.py`](/var/www/html/python/mystatic/firewall-nftables.py)
- [`/var/www/html/python/mystatic/scripts/firewall-nftables.py`](firewall-nftables.py)

### Capabilities:
- **Set-Based nftables Engine**: High-performance kernel-level packet drops with automatic expiry timeouts.
- **Dynamic ARP Whitelisting**: Live auto-discovery of gateway, local IPs, and ARP peers.
- **Payload Inspection**: Drops forbidden file types (`.exe`, `.bat`).
- **Tear Drop Defense**: Blocks malformed fragment offset attacks.
- **Multiple Run Modes**:
  ```bash
  # 1. Interactive Control Menu:
  sudo python firewall-nftables.py

  # 2. Real-Time Autonomous Attack Defense:
  sudo python firewall-nftables.py --monitor

  # 3. Status Report (Safe to run non-root):
  python firewall-nftables.py --status

  # 4. Fast CLI IP / MAC Operations:
  sudo python firewall-nftables.py --block-ip 10.0.0.99
  sudo python firewall-nftables.py --unblock-ip 10.0.0.99
  sudo python firewall-nftables.py --flush
  ```

---

## 5. Modules & Skills Deployment

- **Modules Directory** ([`modules/`](../modules/)):
  - `firewall_nftables.py`, `error.py`, `packet.py`, `route.py`, `router.py`, `interactive_menu.py`, `snifF.py`, `buffering.py`.
  - All expose `process(text)` so they can be dynamically selected by `ai_server.py`.
- **Skills Directory** ([`skills/nftables_firewall/SKILL.md`](../skills/nftables_firewall/SKILL.md)):
  - Full skill documentation exposing firewall control to Ollama (`llama3.2:3b` & `qwen2.5-coder:7b`).
