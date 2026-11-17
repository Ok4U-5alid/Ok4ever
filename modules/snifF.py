#!/usr/bin/env python3


#sudo python sniffer.py -i eth0 -t 4
from scapy.all import *
from scapy.layers.dhcp6 import *
from datetime import datetime
from colorama import Fore, Style, init
from scapy.layers.inet import IP, ICMP, TCP, UDP
from scapy.layers.l2 import ARP
import argparse
import time

init(autoreset=True)
DISPLAY_DELAY = 6.6   # نصف ثانية بين المخرجات
last_display = 0

DHCP6_TYPES = {
    DHCP6_Solicit: "Solicit",
    DHCP6_Advertise: "Advertise",
    DHCP6_Request: "Request",
    DHCP6_Reply: "Reply",
    DHCP6_Renew: "Renew",
    DHCP6_Rebind: "Rebind",
    DHCP6_RelayForward: "Relay-Forward",
    DHCP6_RelayReply: "Relay-Reply"
}

ICMP6_TYPES = {
    ICMPv6ND_RS:         ("ICMPv6 - Router Solicitation", Fore.CYAN),
    ICMPv6ND_RA:         ("ICMPv6 - Router Advertisement", Fore.GREEN),
    ICMPv6ND_NS:         ("ICMPv6 - Neighbor Solicitation", Fore.BLUE),
    ICMPv6ND_NA:         ("ICMPv6 - Neighbor Advertisement", Fore.MAGENTA),
    ICMPv6ND_Redirect:   ("ICMPv6 - Redirect", Fore.LIGHTRED_EX),
    ICMPv6MLReport:      ("ICMPv6 - MLD Report", Fore.LIGHTCYAN_EX),
    ICMPv6MLReport2:     ("ICMPv6 - MLD Report", Fore.LIGHTCYAN_EX),
    ICMPv6MLDone:        ("ICMPv6 - MLD Done", Fore.LIGHTCYAN_EX),
    ICMPv6EchoRequest:   ("ICMPv6 - Echo Request", Fore.LIGHTBLACK_EX),
    ICMPv6EchoReply:     ("ICMPv6 - Echo Reply", Fore.LIGHTBLACK_EX)
}

ARP_TYPES = {
    1: ("ARP Request", Fore.BLUE),
    2: ("ARP Reply", Fore.BLUE)
}


IPV4_PROTOCOLS = {
    ICMP: ("IPv4 ICMP", Fore.BLUE),
    TCP:  ("IPv4 TCP", Fore.BLUE),
    UDP:  ("IPv4 UDP", Fore.BLUE),
    ARP: ("IPV4 ARP", Fore.BLUE),

}

def handle(pkt):
    eth_src = pkt[Ether].src if Ether in pkt else "?"
    eth_dst = pkt[Ether].dst if Ether in pkt else "?"
    ip6_src = pkt[IPv6].src if IPv6 in pkt else "?"
    ip6_dst = pkt[IPv6].dst if IPv6 in pkt else "?"
    #1111000011110000#
    # ARP Detection
    #1111000011110000#

    if ARP in pkt:

        arp_type = pkt[ARP].op

        desc, color = ARP_TYPES.get(
            arp_type,
            ("ARP Unknown", Fore.RED)
        )

        print(color + f"[{datetime.now().strftime('%H:%M:%S')}] {desc}")

        print(f"{Style.DIM}  MAC  {eth_src} -> {eth_dst}") 

        print(
            f"{Style.DIM}  ARP  "
            f"{pkt[ARP].psrc} -> {pkt[ARP].pdst}"
        )

        print(
            f"{Style.DIM}  HW   "
            f"{pkt[ARP].hwsrc}"
        )

        print("-"*60)

        return
    #1111000011110000#
    # IPv4 Detection
    #1111000011110000#

    if IP in pkt:

        src = pkt[IP].src
        dst = pkt[IP].dst


        if ICMP in pkt:
            desc = "IPv4 ICMP"
            color = Fore.CYAN


        elif TCP in pkt:

            desc = f"IPv4 TCP {pkt[TCP].sport}->{pkt[TCP].dport}"
            color = Fore.WHITE


        elif UDP in pkt:

            desc = f"IPv4 UDP {pkt[UDP].sport}->{pkt[UDP].dport}"
            color = Fore.MAGENTA


        else:
            return


        print(color +
              f"[{datetime.now().strftime('%H:%M:%S')}] {desc}")

        print(f"{Style.DIM}  MAC  {eth_src} -> {eth_dst}")
        print(f"{Style.DIM}  IPv4 {src} -> {dst}")

        print("-"*60)

        return

     #1111000011110000#
     # IPv6 Detection
     #1111000011110000#

    if IPv6 in pkt:

        ip6_src = pkt[IPv6].src
        ip6_dst = pkt[IPv6].dst


        for proto, (desc, color) in ICMP6_TYPES.items():

            if proto in pkt:
                break

        else:

            if UDP in pkt and pkt[UDP].dport == 547:

                for dhcp_type, name in DHCP6_TYPES.items():

                    if dhcp_type in pkt:

                        desc = f"DHCPv6 - {name}"
                        color = Fore.YELLOW
                        break

                else:
                    return

            else:
                return

        print(color + f"[{datetime.now().strftime('%H:%M:%S')}] {desc}")
        print(f"{Style.DIM}  MAC  {eth_src} -> {eth_dst}")
        print(f"{Style.DIM}  IPv4  {eth_src} -> {eth_dst}")
        print(f"{Style.DIM}  IPv6 {ip6_src} -> {ip6_dst}")
        print("-"*60)
      # print(Style.RESET_ALL + "-" * 60)

        return            

def get_default_interface() -> str:
    try:
        import subprocess, re
        res = subprocess.run(["ip", "route", "show", "default"], capture_output=True, text=True, timeout=5)
        m = re.search(r"dev (\S+)", res.stdout)
        if m:
            return m.group(1)
    except Exception:
        pass
    return "eth0"

if __name__ == "__main__":
    default_iface = get_default_interface()
    parser = argparse.ArgumentParser(description="IPv6 NDP & DHCPv6 Sniffer")
    parser.add_argument("-i", "--interface", default=default_iface, help=f"Interface to sniff on (default: {default_iface})")
    parser.add_argument("-t", "--time", type=int, default=0, help="Sniff duration (0 = infinite)")
    args = parser.parse_args()

    print(Fore.LIGHTWHITE_EX + f"[*] Sniffing on {args.interface} for {args.time or '∞'} seconds...\n")
    sniff(iface=args.interface, prn=handle, timeout=args.time or None, store=0)

def process(text: str) -> str:
    """Module pre-processor for ai_server."""
    return text
