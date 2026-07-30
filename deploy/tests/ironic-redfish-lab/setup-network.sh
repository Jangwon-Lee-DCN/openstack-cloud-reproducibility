#!/usr/bin/env bash
set -euo pipefail

bridge=br-ironic-poc
tap=tap-ironic0
subnet=172.31.250.0/24
gateway=172.31.250.1
uplink=eno1

case "${1:-up}" in
  up)
    ip link show "$bridge" >/dev/null 2>&1 || ip link add "$bridge" type bridge
    ip address replace "$gateway/24" dev "$bridge"
    ip link set "$bridge" up
    ip link show "$tap" >/dev/null 2>&1 ||
      ip tuntap add dev "$tap" mode tap user ubuntu
    ip link set "$tap" master "$bridge"
    ip link set "$tap" up

    iptables -C FORWARD -i "$bridge" -j ACCEPT 2>/dev/null ||
      iptables -I FORWARD 1 -i "$bridge" -j ACCEPT
    iptables -C FORWARD -o "$bridge" -m conntrack \
      --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null ||
      iptables -I FORWARD 1 -o "$bridge" -m conntrack \
        --ctstate RELATED,ESTABLISHED -j ACCEPT
    iptables -t nat -C POSTROUTING -s "$subnet" -o "$uplink" \
      -j MASQUERADE 2>/dev/null ||
      iptables -t nat -A POSTROUTING -s "$subnet" -o "$uplink" \
        -j MASQUERADE
    ;;
  down)
    iptables -t nat -D POSTROUTING -s "$subnet" -o "$uplink" \
      -j MASQUERADE 2>/dev/null || true
    iptables -D FORWARD -i "$bridge" -j ACCEPT 2>/dev/null || true
    iptables -D FORWARD -o "$bridge" -m conntrack \
      --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || true
    ip link del "$tap" 2>/dev/null || true
    ip link del "$bridge" 2>/dev/null || true
    ;;
  *)
    echo "Usage: $0 [up|down]" >&2
    exit 2
    ;;
esac
