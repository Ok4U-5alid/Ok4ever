#!/bin/bash

# -------------------------
# NFTABLES FIREWALL MENU v3
# With MAC/IP storage + history + exceptions + anti-spoofing
# -------------------------

ip_file="ip_addresses.txt"
mac_file="mac_addresses.txt"
history_file="command_history.txt"

# Create files if missing
for file in "$ip_file" "$mac_file" "$history_file"; do
    [ ! -f "$file" ] && touch "$file"
done

# Log actions
log_history() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" >> "$history_file"
}

# Menu
show_menu() {
    echo "==============================="
    echo " 1. Show current rules"
    echo " 2. Add DROP rule by MAC"
    echo " 3. Add DROP rule by IP"
    echo " 4. Add DROP rule by MAC + IP"
    echo " 5. Flush all rules"
    echo " 6. Show saved IP/MAC"
    echo " 7. Show history"
    echo " 8. Allow specific IP (exception)"
    echo " 9. Allow specific MAC (exception)"
    echo " 10. Block fragmented packets"
    echo " 11. Enable Anti-Spoofing Protection"
    echo " 12. Exit"
    echo "==============================="
}

# DROP by MAC
drop_by_mac() {
    read -p "Enter MAC address: " mac
    sudo nft add rule inet firewall input ether saddr "$mac" drop
    echo "$mac" >> "$mac_file"
    log_history "DROP rule for MAC $mac"
    echo "Added: DROP MAC $mac"
}

# DROP by IP
drop_by_ip() {
    read -p "Enter IP address: " ip
    sudo nft add rule inet firewall input ip saddr "$ip" drop
    echo "$ip" >> "$ip_file"
    log_history "DROP rule for IP $ip"
    echo "Added: DROP IP $ip"
}

# DROP by MAC + IP
drop_by_mac_and_ip() {
    read -p "Enter MAC: " mac
    read -p "Enter IP: " ip
    sudo nft add rule inet firewall input ether saddr "$mac" ip saddr "$ip" drop
    echo "$mac" >> "$mac_file"
    echo "$ip" >> "$ip_file"
    log_history "DROP rule for MAC $mac + IP $ip"
    echo "Added: DROP MAC $mac + IP $ip"
}

# ALLOW specific IP
allow_ip() {
    read -p "Enter IP to ALLOW: " ip
    sudo nft add rule inet firewall input ip saddr "$ip" accept
    log_history "ALLOW rule for IP $ip"
    echo "Added: ALLOW IP $ip"
}

# ALLOW specific MAC
allow_mac() {
    read -p "Enter MAC to ALLOW: " mac
    sudo nft add rule inet firewall input ether saddr "$mac" accept
    log_history "ALLOW rule for MAC $mac"
    echo "Added: ALLOW MAC $mac"
}

# BLOCK fragmented packets
block_fragments() {
    sudo nft add rule inet firewall input frag-off gt 0 drop
    log_history "Blocked fragmented packets"
    echo "Added: DROP all fragmented packets"
}

# Enable anti‑spoofing protection
enable_antispoof() {
    sudo nft add rule inet firewall input fib saddr != oif drop
    log_history "Enabled anti-spoofing protection"
    echo "Anti-spoofing enabled (rpfilter equivalent)"
}

# Show rules
show_rules() {
    sudo nft list ruleset
    log_history "Viewed ruleset"
}

# Flush rules
flush_rules() {
    sudo nft flush ruleset
    log_history "Flushed all rules"
    echo "All firewall rules cleared."
}

# Show saved lists
show_saved() {
    echo "--- Saved IPs ---"
    cat "$ip_file"
    echo ""
    echo "--- Saved MACs ---"
    cat "$mac_file"
    log_history "Viewed saved IP/MAC"
}

# Show history
show_history() {
    echo "--- Command History ---"
    cat "$history_file"
}

# Initialize nft
initialize_nft() {
    sudo nft add table inet firewall 2>/dev/null
    sudo nft add chain inet firewall input '{ type filter hook input priority 0; policy drop; }' 2>/dev/null
}

# MAIN LOOP
initialize_nft

while true; do
    show_menu
    read -p "Choose option: " choice

    case $choice in
        1) show_rules ;;
        2) drop_by_mac ;;
        3) drop_by_ip ;;
        4) drop_by_mac_and_ip ;;
        5) flush_rules ;;
        6) show_saved ;;
        7) show_history ;;
        8) allow_ip ;;
        9) allow_mac ;;
        10) block_fragments ;;
        11) enable_antispoof ;;
        12) echo "Goodbye!"; exit 0 ;;
        *) echo "Invalid choice." ;;
    esac

    echo ""
done
