#sudo nft add rule inet filter input ip saddr 192.168.1.5 drop
#sudo nft add rule bridge filter input ether saddr 08:00:27:71:82:AA drop
#sudo nft add rule inet filter input ip saddr <IP> drop
#sudo nft delete rule inet filter input handle <ID>
#sudo nft -a list chain inet filter input
#sudo nft delete rule inet filter input handle 
#Create nftables table
#sudo nft add table inet firewall
#Create sets
#sudo nft add set inet firewall blocked_ips '{ type ipv4_addr; }'
#sudo nft add set inet firewall blocked_macs '{ type ether_addr; }'
#Add rules
#sudo nft add chain inet firewall input '{ type filter hook input priority 0; }'
#sudo nft add rule inet firewall input ip saddr @blocked_ips drop
#sudo nft add rule inet firewall input ether saddr @blocked_macs drop
#Blocked IPV4 or mac
#sudo nft add element inet firewall blocked_ips { add ipv4 }
#sudo nft add element inet firewall blocked_macs { add mac }


#!/bin/bash
# mytargets-ip_nft.sh
# Interactive network tool (nftables edition) — replaces ufw/iptables with nft sets
# Save as mytargets-ip_nft.sh, chmod +x mytargets-ip_nft.sh, run with sudo

set -o errexit
set -o nounset
set -o pipefail

echo "Welcome to the Interactive Network Tool (nftables edition)"
echo "Type 'help' to see the list of available commands."

ip_file="ip-freecode.txt"
history_file="freecode_history.txt"

# Ensure files exist
for file in "$ip_file" "$history_file"; do
    [ ! -f "$file" ] && : > "$file"
done

# --- Helpers for nft environment ---
ensure_nft_environment() {
    # Create table if missing
    if ! nft list table inet firewall >/dev/null 2>&1; then
        sudo nft add table inet firewall
    fi

    # Create IPv4 set for blocked IPs (fast lookups)
    if ! nft list set inet firewall blocked_ips >/dev/null 2>&1; then
        sudo nft add set inet firewall blocked_ips { type ipv4_addr\; flags interval\; }
    fi

    # Create chain if missing
    if ! nft list chain inet firewall input >/dev/null 2>&1; then
        sudo nft add chain inet firewall input { type filter hook input priority 0\; policy accept\; }
    fi

    # Add drop rule for set membership (if not already present)
    if ! sudo nft list ruleset | grep -q "ip saddr @blocked_ips drop"; then
        sudo nft add rule inet firewall input ip saddr @blocked_ips drop || true
    fi
}

# Initialize nft environment
ensure_nft_environment

# --- Validations & utilities ---
is_valid_ipv4() {
    local ip=$1
    if [[ $ip =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
        IFS='.' read -r -a o <<< "$ip"
        for oct in "${o[@]}"; do
            (( oct >= 0 && oct <= 255 )) || return 1
        done
        return 0
    fi
    return 1
}

save_command_to_history() {
    echo "$(date +'%Y-%m-%d %H:%M:%S') - $1" >> "$history_file"
}

# Get local IPv4 addresses to auto-exclude (won't block these)
get_local_ipv4s() {
    ip -4 addr show scope global | awk '/inet/ {print $2}' | cut -d'/' -f1 || true
}

# store local IPs in an array (exclude these from blocking)
declare -a LOCAL_IPS
while IFS= read -r lip; do
    LOCAL_IPS+=( "$lip" )
done < <(get_local_ipv4s)

is_local_ip() {
    local candidate=$1
    for l in "${LOCAL_IPS[@]}"; do
        [ "$candidate" == "$l" ] && return 0
    done
    return 1
}

# --- Blocking functions using nft sets ---
block_ip_nft() {
    local ip_to_block=$1
    if [ -z "$ip_to_block" ]; then
        echo "No IP provided."
        return 1
    fi
    if ! is_valid_ipv4 "$ip_to_block"; then
        echo "Invalid IPv4 address: $ip_to_block"
        return 1
    fi
    if is_local_ip "$ip_to_block"; then
        echo "Refusing to block local host IP: $ip_to_block"
        return 1
    fi

    echo "Blocking IP (nft): $ip_to_block"
    sudo nft add element inet firewall blocked_ips { "$ip_to_block" } 2>/dev/null || true

    # track locally for clear/unblock
    if ! grep -q -F "$ip_to_block" "$ip_file"; then
        echo "$ip_to_block" >> "$ip_file"
    fi
    echo "Blocked $ip_to_block"
}

unblock_ip_nft() {
    local ip_to_unblock=$1
    if [ -z "$ip_to_unblock" ]; then
        echo "Usage: unblock_ip <ipv4>"
        return 1
    fi
    echo "Unblocking IP (nft): $ip_to_unblock"
    sudo nft delete element inet firewall blocked_ips { "$ip_to_unblock" } 2>/dev/null || true
    grep -v -F "$ip_to_unblock" "$ip_file" > "${ip_file}.tmp" && mv "${ip_file}.tmp" "$ip_file" || true
    echo "Unblocked $ip_to_unblock"
}

# Clear all tracked blocks
clear_blocks_nft() {
    echo "Clearing nftables blocks added by this script..."
    while IFS= read -r ip; do
        [ -z "$ip" ] && continue
        sudo nft delete element inet firewall blocked_ips { "$ip" } 2>/dev/null || true
    done < "$ip_file"
    : > "$ip_file"
    echo "Cleared tracked blocks (local tracking file reset)."
    echo "Note: other nft rules not created by this script are untouched."
}

# --- tcpdump control ---
tcpdump_pid=""
stop_tcpdump() {
    if [ -n "${tcpdump_pid}" ]; then
        if kill "$tcpdump_pid" 2>/dev/null; then
            echo "tcpdump (PID $tcpdump_pid) stopped."
            tcpdump_pid=""
        else
            echo "Failed to stop tcpdump (maybe already stopped)."
            tcpdump_pid=""
        fi
    else
        echo "No tcpdump process is running."
    fi
}

# Add/check new device by IP (called from tcpdump output)
check_new_device_ip() {
    local new_device=$1
    if [ -z "$new_device" ]; then return 1; fi
    if ! is_valid_ipv4 "$new_device"; then return 1; fi
    if grep -q -F "$new_device" "$ip_file"; then
        return 1
    fi
    # prevent blocking local host IPs
    if is_local_ip "$new_device"; then
        echo "Seen local IP (ignored): $new_device"
        return 1
    fi
    echo "$new_device" >> "$ip_file"
    echo "New device detected (IP): $new_device"
    block_ip_nft "$new_device"
    return 0
}

# --- interactive loop ---
while true; do
    echo -n "network-tool> "
    read -r command args
    save_command_to_history "$command $args"

    case $command in
        help)
            cat <<'EOF'
Available commands:
  sniff <iface>       - Start tcpdump (Example: sniff eth0)
  stop                - Stop tcpdump
  ip                  - Show IP addresses (ip addr show)
  routes              - Show routing table (ip route show)
  ps                  - Show process list (ps -aux)
  htop                - Show htop (if installed)
  clear_blocks        - Clear all tracked nftables blocks added by this script
  list_blocks         - List blocked IPs (nft and local file)
  unblock_ip <ip>     - Unblock a specific IP that was added
  quit                - Exit the tool
EOF
            ;;

        sniff)
            if [[ -z "$args" ]]; then
                echo "Please specify a network interface (e.g., eth0)."
            else
                echo "Starting tcpdump on interface $args (press 'stop' to end)"
                sudo tcpdump -i "$args" -l -nn -e 'arp or ip or ip6' | while read -r line; do
                    ip_source=$(echo "$line" | grep -oE "[0-9]{1,3}(\.[0-9]{1,3}){3}" | head -n1 || true)
                    ip_dest=$(echo "$line" | grep -oE "[0-9]{1,3}(\.[0-9]{1,3}){3}" | tail -n1 || true)

                    if [ -n "$ip_source" ]; then
                        check_new_device_ip "$ip_source" || true
                    fi
                    if [ -n "$ip_dest" ] && [ "$ip_dest" != "$ip_source" ]; then
                        check_new_device_ip "$ip_dest" || true
                    fi
                done &
                tcpdump_pid=$!
                echo "tcpdump started with PID $tcpdump_pid"
            fi
            ;;

        stop)
            stop_tcpdump
            ;;

        ip)
            echo "Fetching IP addresses..."
            ip addr show
            ;;

        routes)
            echo "Fetching routing table..."
            ip route show
            ;;

        ps)
            echo "Fetching process list..."
            ps -aux
            ;;

        htop)
            if command -v htop >/dev/null 2>&1; then
                htop
            else
                echo "htop not installed. Try: sudo apt install htop"
            fi
            ;;

        clear_blocks)
            clear_blocks_nft
            ;;

        list_blocks)
            echo "Blocked IPs (nft set):"
            sudo nft list set inet firewall blocked_ips || true
            echo ""
            echo "Local tracked file: $ip_file"
            echo "Entries: $(wc -l < "$ip_file")"
            ;;

        unblock_ip)
            if [[ -z "$args" ]]; then
                echo "Usage: unblock_ip <ipv4>"
            else
                unblock_ip_nft "$args"
            fi
            ;;

        quit)
            echo "Exiting. Stopping tcpdump (if running)."
            stop_tcpdump
            break
            ;;

        *)
            echo "Unknown command: $command"
            echo "Type 'help' to see the list of available commands."
            ;;
    esac
done

