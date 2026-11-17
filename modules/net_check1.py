# modules/net_check.py
"""Pre-processing module: audits THIS machine's network and appends a report
to the message, so the LLM can explain it.

Report: IPv4/IPv6 addresses and routes, your watched interfaces (wg0, eth0,
wg0-iphone-ipad), WireGuard peers, internet reachability over IPv4 and IPv6,
listening ports with their owning process, established connections (what
`netstat -natp` showed), firewall policy, and running services.

Read-only. It only looks at the local host and never scans other machines.
Packet capture (tshark/tcpdump) needs root, so it stays in network_monitor_menu.sh.

Standalone:  python3 modules/net_check.py
             sudo python3 modules/net_check.py   (also shows every process, nft rules, WireGuard peers)
"""

import os
import re
import socket
import subprocess
import time
from collections import Counter
from datetime import datetime

# Same interface list as network_monitor_menu.sh
WATCHED_INTERFACES = ["wg0", "eth0", "wg0-iphone-ipad"]

MAX_CHARS = 7500          # keep the prompt small for local models
ALL_IFACES = {"0.0.0.0", "*", "::"}
COMMON_SERVICES = ["ssh", "apache2", "nginx", "postgresql", "mariadb", "mysql",
                   "docker", "ollama", "nftables", "NetworkManager", "ufw", "fail2ban"]
PROC_RE = re.compile(r'\(\("([^"]+)"')
NET = "/sys/class/net"


def _run(cmd, timeout=8):
    """Run a command (no shell) and return (returncode, text)."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or p.stderr).strip()
    except FileNotFoundError:
        return 127, f"{cmd[0]} is not installed"
    except subprocess.TimeoutExpired:
        return 124, f"{cmd[0]} timed out"


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def _cap(text, limit):
    """Cut text to `limit` characters at a line boundary."""
    if len(text) <= limit:
        return text
    return text[:limit].rsplit("\n", 1)[0] + "\n... (cut)"


def _mb(n):
    return f"{n / 1e6:.1f} MB"


def _reach(host, port, family):
    try:
        with socket.socket(family, socket.SOCK_STREAM) as s:
            s.settimeout(3)
            s.connect((host, port))
        return "reachable"
    except OSError as exc:
        return f"NOT reachable ({exc})"


def _addresses():
    blocks = []
    for fam in ("4", "6"):
        _, addr = _run(["ip", "-br", f"-{fam}", "addr"])
        _, route = _run(["ip", f"-{fam}", "route", "show", "default"])
        blocks.append(f"IPv{fam} addresses:\n{addr or 'none'}\n"
                      f"IPv{fam} default route: {route or 'none'}")
    return "\n\n".join(blocks)


def _interfaces():
    present = sorted(os.listdir(NET)) if os.path.isdir(NET) else []
    lines = []
    for name in WATCHED_INTERFACES:
        if name not in present:
            lines.append(f"{name}: not present")
            continue
        state = _read(f"{NET}/{name}/operstate") or "?"
        rx = int(_read(f"{NET}/{name}/statistics/rx_bytes") or 0)
        tx = int(_read(f"{NET}/{name}/statistics/tx_bytes") or 0)
        lines.append(f"{name}: state {state}, received {_mb(rx)}, sent {_mb(tx)}")
    others = [n for n in present if n not in WATCHED_INTERFACES]
    lines.append("other interfaces: " + (", ".join(others) or "none"))
    return "\n".join(lines)


def _wireguard():
    wg = [n for n in (os.listdir(NET) if os.path.isdir(NET) else []) if n.startswith("wg")]
    if not wg:
        return "no WireGuard interfaces present"
    lines = []
    for name in wg:
        rc, text = _run(["wg", "show", name, "latest-handshakes"])
        if rc == 127:
            lines.append(f"{name}: wg tool not installed (sudo apt install wireguard-tools)")
            continue
        if rc:
            first = text.splitlines()[0] if text else "error"
            lines.append(f"{name}: cannot read peers ({first}); run with sudo")
            continue
        ages = []
        for row in text.splitlines():
            parts = row.split("\t")
            if len(parts) == 2 and parts[1].isdigit():
                ts = int(parts[1])
                ages.append("never" if ts == 0 else f"{int(time.time() - ts)}s ago")
        lines.append(f"{name}: {len(ages)} peer(s), last handshakes: {', '.join(ages) or 'none'}")
    return "\n".join(lines)


def _connectivity():
    return (f"IPv4 internet (1.1.1.1 port 53): {_reach('1.1.1.1', 53, socket.AF_INET)}\n"
            f"IPv6 internet (2606:4700:4700::1111 port 53): "
            f"{_reach('2606:4700:4700::1111', 53, socket.AF_INET6)}")


def _ports():
    rc, out = _run(["ss", "-H", "-tulnp"])
    if rc:
        return f"ss failed: {out}"
    rows, seen = [], set()
    for line in out.splitlines():
        f = line.split(None, 6)
        if len(f) < 5:
            continue
        proto, local = f[0], f[4]
        addr, _, port = local.rpartition(":")
        addr = addr.strip("[]").split("%")[0]
        if (proto, addr, port) in seen or not port.isdigit():
            continue
        seen.add((proto, addr, port))
        owner = PROC_RE.search(f[6]) if len(f) > 6 else None
        if addr in ALL_IFACES:
            scope, local_only = "ALL INTERFACES", False
        elif addr.startswith("127.") or addr == "::1":
            scope, local_only = "localhost only", True
        else:
            scope, local_only = f"bound to {addr}", False
        try:
            svc = socket.getservbyport(int(port), "udp" if proto.startswith("udp") else "tcp")
        except OSError:
            svc = "?"
        rows.append((local_only, int(port), proto, scope, svc,
                     owner.group(1) if owner else "(owner hidden: needs root)"))
    rows.sort()
    exposed = sum(1 for r in rows if not r[0])
    lines = [f"{len(rows)} listening sockets, {exposed} not limited to localhost "
             "(a firewall may still block them)"]
    lines += [f"{p:<4} {port:<6} {scope:<16} {svc:<10} {who}"
              for _, port, p, scope, svc, who in rows]
    return "\n".join(lines)


def _connections():
    rc, out = _run(["ss", "-H", "-tnp"])
    if rc:
        return f"ss failed: {out}"
    remotes, procs, total = Counter(), {}, 0
    for line in out.splitlines():
        f = line.split(None, 5)
        if len(f) < 5 or f[0] != "ESTAB":
            continue
        total += 1
        peer = f[4].rpartition(":")[0].strip("[]")
        remotes[peer] += 1
        m = PROC_RE.search(f[5]) if len(f) > 5 else None
        if m:
            procs.setdefault(peer, set()).add(m.group(1))
    lines = [f"{total} established TCP connections (top remote addresses):"]
    lines += [f"{peer:<40} {n:>3}  {', '.join(sorted(procs.get(peer, ()))) or '-'}"
              for peer, n in remotes.most_common(10)]
    return "\n".join(lines)


def _firewall():
    rc, out = _run(["nft", "list", "ruleset"])
    if rc:
        first = out.splitlines()[0] if out else "no output"
        return f"nftables: cannot read ({first}); run with sudo to see the rules"
    hooks = [l.strip() for l in out.splitlines() if "hook" in l]
    return "nftables base chains: " + ("; ".join(hooks) if hooks else "none (no firewall rules loaded)")


def _services():
    rc, out = _run(["systemctl", "list-units", "--type=service", "--state=running",
                    "--no-legend", "--plain", "--no-pager"])
    running = [l.split()[0].removesuffix(".service") for l in out.splitlines() if l.strip()] if rc == 0 else []
    common = []
    for name in COMMON_SERVICES:
        _, state = _run(["systemctl", "is-active", name])
        common.append(f"{name}: {state.splitlines()[0] if state else '?'}")
    shown = ", ".join(running[:40]) + (" ..." if len(running) > 40 else "")
    return (f"{len(running)} services running: {shown or 'unknown'}\n\n"
            "Common services:\n" + "\n".join(common))


def report() -> str:
    sections = [
        ("Host", f"{socket.gethostname()} at {datetime.now().astimezone().isoformat(timespec='seconds')}", 300),
        ("Addresses and routes", _addresses(), 1100),
        ("Watched interfaces", _interfaces(), 700),
        ("WireGuard", _wireguard(), 500),
        ("Internet reachability", _connectivity(), 300),
        ("Listening ports", _ports(), 1900),
        ("Established connections", _connections(), 1000),
        ("Firewall", _firewall(), 400),
        ("Services", _services(), 1300),
    ]
    text = "\n\n".join(f"## {title}\n{_cap(body, limit)}" for title, body, limit in sections)
    return text[:MAX_CHARS]


def process(text: str) -> str:
    request = text.strip() or "Check my network."
    return (f"{request}\n\n--- network report (this machine) ---\n{report()}\n--- end report ---\n"
            "Using only the report above, say what is running, what is reachable from other "
            "machines, whether IPv4, IPv6 and WireGuard work, and any risks.")


if __name__ == "__main__":
    print(report())
