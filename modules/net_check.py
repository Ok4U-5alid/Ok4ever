# modules/net_check.py
"""Pre-processing module: audits THIS machine's network and appends a report
(IPv4/IPv6 addresses and routes, internet reachability, listening ports with
their owning process, firewall policy, running services) to the message, so
the LLM can explain it.

Read-only. It only looks at the local host; it never scans other machines.

Standalone:  python3 modules/net_check.py
             sudo python3 modules/net_check.py   (also shows every process + nft rules)
"""

import re
import socket
import subprocess
from datetime import datetime

MAX_CHARS = 7000          # keep the prompt small for local models
ALL_IFACES = {"0.0.0.0", "*", "::"}
COMMON_SERVICES = ["ssh", "apache2", "nginx", "postgresql", "mariadb", "mysql",
                   "docker", "ollama", "nftables", "NetworkManager", "ufw", "fail2ban"]


def _run(cmd, timeout=8):
    """Run a command (no shell) and return (returncode, text)."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or p.stderr).strip()
    except FileNotFoundError:
        return 127, f"{cmd[0]} is not installed"
    except subprocess.TimeoutExpired:
        return 124, f"{cmd[0]} timed out"


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
        owner = re.search(r'\(\("([^"]+)"', f[6]) if len(f) > 6 else None
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
        ("Host", f"{socket.gethostname()} at {datetime.now().astimezone().isoformat(timespec='seconds')}"),
        ("Addresses and routes", _addresses()),
        ("Internet reachability", _connectivity()),
        ("Listening ports", _ports()),
        ("Firewall", _firewall()),
        ("Services", _services()),
    ]
    text = "\n\n".join(f"## {title}\n{body}" for title, body in sections)
    return text[:MAX_CHARS]


def process(text: str) -> str:
    request = text.strip() or "Check my network."
    return (f"{request}\n\n--- network report (this machine) ---\n{report()}\n--- end report ---\n"
            "Using only the report above, say what is running, what is reachable from other "
            "machines, whether IPv4 and IPv6 work, and any risks.")


if __name__ == "__main__":
    print(report())
