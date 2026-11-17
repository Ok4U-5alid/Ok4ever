#!/usr/bin/env bash
# r_nft_bash5_live.sh — nftables toolkit + WireGuard rotation + live traffic monitor
# Requires Bash 5+, nft, iproute2, systemd, tcpdump, tshark, awk, setsid, and sudo.

set -Eeuo pipefail
IFS=$'\n\t'

readonly SCRIPT_NAME=${0##*/}
readonly -a WG_UNITS=(wg0 wg01 wg02 wg03 wg04)
readonly WG_DELAY=${WG_DELAY:-4}  # seconds between WireGuard interface rotations
readonly MONITOR_DELAY=${MONITOR_DELAY:-1}
readonly CAPTURE_FILTER=${CAPTURE_FILTER:-}
readonly -a WG_IFACES=(wg0 wg01 wg02 wg03 wg04)

# ---------- UI ----------
color() { printf '\033[%sm' "$1"; }
reset_color() { printf '\033[0m'; }
info() { printf '%s[*]%s %s\n' "$(color 36)" "$(reset_color)" "$*"; }
warn() { printf '%s[!]%s %s\n' "$(color 33)" "$(reset_color)" "$*" >&2; }
error() { printf '%s[ERROR]%s %s\n' "$(color 31)" "$(reset_color)" "$*" >&2; }
pause_screen() { read -r -p $'\nPress Enter to continue' _ || true; }

show_menu() {

  cat <<'MENU'
          
  1) Show IP addresses                    
  2) Show listening ports                 
  3) Show Tor process                     
  4) Display nftables ruleset              
  5) Add DROP rule by MAC                  
  6) Add DROP rule by IP                   
  7) Add DROP rule by MAC + IP              
  8) Flush ALL nftables rules (danger)     
  9) Continuous WireGuard rotation          
 10) Live monitor + WireGuard rotation      
  0) Exit                                   

MENU
}

# ---------- Preconditions / cleanup ----------
require_commands() {
  local cmd
  for cmd in nft ip ss systemctl tcpdump tshark awk setsid; do
    command -v "$cmd" >/dev/null 2>&1 || { error "Missing command: $cmd"; return 1; }
  done
}

monitor_pids=()
_saved_stty=''
cleanup_monitor() {
  local pid
  for pid in "${monitor_pids[@]}"; do
    kill -- -"$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
  done
  for pid in "${monitor_pids[@]}"; do wait "$pid" 2>/dev/null || true; done
  monitor_pids=()
}
cleanup() {
  [[ -n $_saved_stty ]] && stty "$_saved_stty" 2>/dev/null || true
  cleanup_monitor
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM HUP

# ---------- nftables ----------
ensure_nft_table() {
  sudo nft list table inet firewall >/dev/null 2>&1 || sudo nft add table inet firewall
  sudo nft list chain inet firewall input >/dev/null 2>&1 || \
    sudo nft add chain inet firewall input '{ type filter hook input priority 0; policy accept; }'
}

read_value() {
  local prompt=$1 result
  read -r -p "$prompt" result || return 1
  [[ -n $result ]] || { warn 'Input cannot be empty.'; return 1; }
  REPLY=$result
}

add_drop_mac() {
  local mac
  read_value 'MAC address: ' || return
  mac=$REPLY
  sudo nft add rule inet firewall input ether saddr "$mac" counter drop
  info "Added DROP rule for MAC $mac"
}
add_drop_ip() {
  local ip
  read_value 'IP address: ' || return
  ip=$REPLY
  sudo nft add rule inet firewall input ip saddr "$ip" counter drop
  info "Added DROP rule for IP $ip"
}
add_drop_mac_ip() {
  local mac ip
  read_value 'MAC address: ' || return; mac=$REPLY
  read_value 'IPv4 address: ' || return; ip=$REPLY
  sudo nft add rule inet firewall input ether saddr "$mac" ip saddr "$ip" counter drop
  info "Added DROP rule for MAC $mac + IP $ip"
}
show_nft_rules() { sudo nft list ruleset; }
flush_nft_rules() {
  warn 'This removes every table and rule in the entire nftables ruleset.'
  read -r -p 'Type FLUSH to confirm: ' confirmation || return
  [[ $confirmation == FLUSH ]] || { info 'Cancelled.'; return; }
  sudo nft flush ruleset
  info 'Ruleset flushed.'
}

# ---------- WireGuard rotation ----------
wg_is_active() { systemctl is-active --quiet "wg-quick@$1"; }
wg_start() {
  local unit=$1
  info "Starting $unit"
  sudo systemctl start "wg-quick@$unit" || { warn "Could not start $unit"; return 1; }
}
wg_stop() {
  local unit=$1
  info "Stopping $unit"
  sudo systemctl stop "wg-quick@$unit" || { warn "Could not stop $unit"; return 1; }
}
wait_or_exit_cycle() {
  local seconds=$1 key='' elapsed=0
  while (( elapsed < seconds )); do
    printf '\rNext transition in %2d s — press Ctrl+X to return to menu ' "$((seconds-elapsed))"
    if IFS= read -r -s -n 1 -t 1 key; then
      if [[ $key == $'\x18' ]]; then printf '\n'; return 10; fi
    fi
    ((elapsed+=1))
  done
  printf '\n'
  return 0
}

wg_cycle() {
  local current next i rc
  info 'Continuous WireGuard rotation started. Ctrl+X returns to menu.'
  sudo -v || return
  current=''
  for unit in "${WG_UNITS[@]}"; do
    if wg_is_active "$unit"; then current=$unit; break; fi
  done
  [[ -n $current ]] || current=${WG_UNITS[0]}

  while :; do
    for ((i=0; i<${#WG_UNITS[@]}; i++)); do
      [[ ${WG_UNITS[i]} == "$current" ]] || continue
      next=${WG_UNITS[$(((i+1) % ${#WG_UNITS[@]}))]}
      wg_stop "$current" || true
      sleep 1
      wg_start "$next" || true
      current=$next
      wait_or_exit_cycle "$WG_DELAY"; rc=$?
      if (( rc == 10 )); then info 'Rotation stopped by user.'; return 0; fi
    done
  done
}

# ---------- Live traffic monitor workers ----------
iface_exists() { ip link show dev "$1" >/dev/null 2>&1; }

capture_loop() {
  local tool=$1 iface=$2 rc
  while :; do
    if ! iface_exists "$iface"; then sleep "$MONITOR_DELAY"; continue; fi
    printf '[START:%s:%s] capture attached\n' "$tool" "$iface"

    if [[ $tool == tcpdump ]]; then
      if [[ -n $CAPTURE_FILTER ]]; then
        sudo -n stdbuf -oL tcpdump -l -nn -tttt -i "$iface" "$CAPTURE_FILTER" 2>&1
      else
        sudo -n stdbuf -oL tcpdump -l -nn -tttt -i "$iface" 2>&1
      fi
    else
      if [[ -n $CAPTURE_FILTER ]]; then
        sudo -n stdbuf -oL tshark -l -n -i "$iface" -Y "$CAPTURE_FILTER" \
          -T fields -E separator='|' -E quote=d -E occurrence=f \
          -e frame.time -e frame.interface_name -e ip.src -e ip.dst \
          -e ipv6.srcip -e ipv6.dstip -e tcp.srcport -e tcp.dstport \
          -e udp.srcport -e udp.dstport -e frame.protocols 2>&1
      else
        sudo -n stdbuf -oL tshark -l -n -i "$iface" \
          -T fields -E separator='|' -E quote=d -E occurrence=f \
          -e frame.time -e frame.interface_name -e ip.src -e ip.dst \
          -e ipv6.srcip -e ipv6.dstip -e tcp.srcport -e tcp.dstport \
          -e udp.srcport -e udp.dstport -e frame.protocols 2>&1
      fi
    fi | awk -v tag="[$tool:$iface]" '
      /pcap_loop: The interface disappeared/ { next }
      /^Capturing on / { next }
      { print tag, $0; fflush() }
    '
    rc=${PIPESTATUS[0]:-0}
    if ! iface_exists "$iface"; then
      printf '[WAIT:%s:%s] interface disappeared; auto-reconnecting\n' "$tool" "$iface"
    elif (( rc != 0 )); then
      printf '[RETRY:%s:%s] capture exited (status %d); retrying\n' "$tool" "$iface" "$rc"
    else
      printf '[RETRY:%s:%s] capture ended; retrying\n' "$tool" "$iface"
    fi
    sleep "$MONITOR_DELAY"
  done
}

start_monitor_worker() {
  local tool=$1 iface=$2
  setsid bash -c 'capture_loop "$1" "$2"' _ "$tool" "$iface" &
  monitor_pids+=("$!")
}

start_live_monitor() {
  sudo -v || return 1
  sudo -n true 2>/dev/null || { error 'sudo credentials are not cached'; return 1; }
  export MONITOR_DELAY CAPTURE_FILTER
  export -f iface_exists capture_loop
  info 'Starting tcpdump + tshark workers for all WireGuard interfaces'
  for iface in "${WG_IFACES[@]}"; do
    start_monitor_worker tcpdump "$iface"
    start_monitor_worker tshark "$iface"
  done
  info 'Live capture workers started in this terminal.'
}

combined_live_cycle() {
  start_live_monitor || return 1
  # Always stop all capture workers when the rotation exits or is interrupted.
  wg_cycle
  cleanup_monitor
  info 'Live monitor stopped; returned to menu.'
}

# ---------- Main ----------
main() {
  require_commands || exit 1
  sudo -v || exit 1
  ensure_nft_table

  while :; do
    show_menu
    read -r -p 'Select: ' choice || { printf '\n'; break; }
    case $choice in
      1) ip -brief address show; pause_screen ;;
      2) ss -tuln; pause_screen ;;
      3) pgrep -a tor || info 'Tor process not found.'; pause_screen ;;
      4) show_nft_rules; pause_screen ;;
      5) add_drop_mac; pause_screen ;;
      6) add_drop_ip; pause_screen ;;
      7) add_drop_mac_ip; pause_screen ;;
      8) flush_nft_rules; pause_screen ;;
      9) wg_cycle; pause_screen ;;
      10) combined_live_cycle; pause_screen ;;
      0) info 'Goodbye.'; break ;;
      *) warn 'Invalid selection.'; pause_screen ;;
    esac
  done
}

main "$@"
