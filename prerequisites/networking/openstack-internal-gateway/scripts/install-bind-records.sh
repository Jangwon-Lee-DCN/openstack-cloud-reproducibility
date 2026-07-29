#!/usr/bin/env bash
set -euo pipefail

STACK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ZONE_DIR=/etc/bind/zones
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

sudo -n named-checkzone dcn.ssu.ac.kr "${STACK_DIR}/bind/db.dcn.ssu.ac.kr"
sudo -n named-checkzone 21.168.192.in-addr.arpa "${STACK_DIR}/bind/db.192.168.21"

sudo -n install -m 0644 "${ZONE_DIR}/db.dcn.ssu.ac.kr" \
  "${ZONE_DIR}/db.dcn.ssu.ac.kr.before-internal-gateway-${STAMP}"
sudo -n install -m 0644 "${ZONE_DIR}/db.192.168.21" \
  "${ZONE_DIR}/db.192.168.21.before-internal-gateway-${STAMP}"
sudo -n install -o bind -g bind -m 0644 "${STACK_DIR}/bind/db.dcn.ssu.ac.kr" \
  "${ZONE_DIR}/db.dcn.ssu.ac.kr"
sudo -n install -o bind -g bind -m 0644 "${STACK_DIR}/bind/db.192.168.21" \
  "${ZONE_DIR}/db.192.168.21"
sudo -n rndc reload dcn.ssu.ac.kr
sudo -n rndc reload 21.168.192.in-addr.arpa

for dns_server in 192.168.21.10 192.168.21.12; do
  test "$(dig +short @"${dns_server}" api.internal.cloud.dcn.ssu.ac.kr A)" = 192.168.21.7
done
test "$(dig +short @192.168.21.10 -x 192.168.21.7)" = api.internal.cloud.dcn.ssu.ac.kr.
echo "BIND forward and reverse records for the internal API Gateway are active."
