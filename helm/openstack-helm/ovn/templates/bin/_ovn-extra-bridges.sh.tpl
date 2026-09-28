{{- if .Values.conf.ovn_node_extra_bridges }}
# BEGIN operator-selected addressless VLAN bridges
# Do not infer a service attachment from interface presence or a rack label.
extra_bridges=""
case "$NODE_NAME" in
{{- range $node, $entries := .Values.conf.ovn_node_extra_bridges }}
{{- if not (regexMatch "^[a-z0-9][a-z0-9.-]*$" $node) }}{{ fail "invalid extra bridge node name" }}{{ end }}
{{- $physnets := dict }}{{- $bridges := dict }}{{- $interfaces := dict }}
  {{ $node }})
    extra_bridges='{{ range $entry := $entries }}
{{- range $key := list "physnet" "bridge" "interface" "parent" }}
{{- if not (regexMatch "^[a-z][a-z0-9-]{0,14}$" (toString (index $entry $key))) }}{{ fail (printf "invalid extra bridge %s" $key) }}{{ end }}
{{- end }}
{{- if or (has $entry.bridge (list "br-ex" "br-int")) (eq $entry.interface $entry.parent) (eq $entry.interface $entry.bridge) }}{{ fail "extra bridge cannot replace existing base or parent interfaces" }}{{ end }}
{{- if or (hasKey $physnets $entry.physnet) (hasKey $bridges $entry.bridge) (hasKey $interfaces $entry.interface) }}{{ fail "duplicate extra physnet, bridge or interface" }}{{ end }}
{{- $_ := set $physnets $entry.physnet true }}{{- $_ := set $bridges $entry.bridge true }}{{- $_ := set $interfaces $entry.interface true }}
{{- if not (regexMatch "^[0-9]+$" (toString $entry.vlan)) }}{{ fail "invalid extra VLAN ID" }}{{ end }}
{{- if or (lt (int $entry.vlan) 2) (gt (int $entry.vlan) 4094) }}{{ fail "extra VLAN ID out of range" }}{{ end }}
{{ printf "%s %s %s %s %d\n" $entry.physnet $entry.bridge $entry.interface $entry.parent (int $entry.vlan) }}{{ end }}'
    ;;
{{- end }}
esac

if [[ -n "${extra_bridges//[[:space:]]/}" ]]; then
  ovs-vsctl --timeout=10 show >/dev/null
  # Validate every selected interface before creating any bridge or port.
  while read -r physnet bridge iface parent vlan; do
    [[ -n "$physnet" ]] || continue
    case ",$bridge_mappings," in
      *",$physnet:"*) echo "Extra physnet collides with base mapping" >&2; exit 1 ;;
    esac
    iface_state=$(ip -d -o link show dev "$iface")
    [[ "$iface_state" == *" $iface@$parent:"* ]] || { echo "Wrong VLAN parent" >&2; exit 1; }
    grep -Eq "vlan protocol 802.1Q id $vlan([[:space:]]|$)" <<< "$iface_state" || { echo "Wrong VLAN identity" >&2; exit 1; }
    [[ -z "$(ip -o addr show dev "$iface")" ]] || { echo "Service VLAN has host addresses" >&2; exit 1; }
    attached=$(ovs-vsctl --timeout=10 port-to-br "$iface" 2>/dev/null || true)
    [[ -z "$attached" || "$attached" == "$bridge" ]] || { echo "Service VLAN belongs to another bridge" >&2; exit 1; }
    if ovs-vsctl --timeout=10 br-exists "$bridge"; then
      owner=$(ovs-vsctl --timeout=10 get Bridge "$bridge" external_ids:dcn-managed-physnet | tr -d '"')
      [[ "$owner" == "$physnet" ]] || { echo "Refusing to adopt unowned bridge" >&2; exit 1; }
      [[ -z "$(ip -o addr show dev "$bridge")" ]] || { echo "Service bridge has host addresses" >&2; exit 1; }
      bridge_ports=$(ovs-vsctl --timeout=10 list-ports "$bridge")
      while read -r port; do
        [[ -n "$port" && "$port" != "$iface" ]] || continue
        # OVN creates localnet patch pairs after first initialization. Retain
        # only reciprocal, marked pairs to br-int, not arbitrary extra ports.
        kind=$(ovs-vsctl --timeout=10 get Interface "$port" type | tr -d '"')
        localnet=$(ovs-vsctl --timeout=10 get Port "$port" external_ids:ovn-localnet-port | tr -d '"')
        [[ "$kind" == patch && "$localnet" =~ ^[a-zA-Z0-9_-]+$ ]] || { echo "Unexpected service bridge port" >&2; exit 1; }
        peer=$(ovs-vsctl --timeout=10 get Interface "$port" options:peer | tr -d '"')
        [[ "$peer" =~ ^[a-zA-Z0-9_-]+$ ]] || { echo "Invalid patch peer" >&2; exit 1; }
        [[ "$(ovs-vsctl --timeout=10 port-to-br "$peer")" == br-int ]] || { echo "Patch peer is not on br-int" >&2; exit 1; }
        [[ "$(ovs-vsctl --timeout=10 get Interface "$peer" type | tr -d '"')" == patch ]] || exit 1
        [[ "$(ovs-vsctl --timeout=10 get Interface "$peer" options:peer | tr -d '"')" == "$port" ]] || exit 1
        [[ "$(ovs-vsctl --timeout=10 get Port "$peer" external_ids:ovn-localnet-port | tr -d '"')" == "$localnet" ]] || exit 1
      done <<< "$bridge_ports"
    fi
  done <<< "$extra_bridges"
  while read -r physnet bridge iface parent vlan; do
    [[ -n "$physnet" ]] || continue
    ovs-vsctl --timeout=10 --may-exist add-br "$bridge" -- set Bridge "$bridge" protocols=OpenFlow13 external_ids:dcn-managed-physnet="$physnet"
    ovs-vsctl --timeout=10 --may-exist add-port "$bridge" "$iface"
    ip link set dev "$bridge" addrgenmode none
    # The newly created, provider-owned internal interface can acquire an
    # automatic link-local address before addrgenmode is changed. Never touch
    # the physical parent or any existing addressed interface.
    ip -6 addr flush dev "$bridge" scope link
    ip link set dev "$bridge" up
    [[ -z "$(ip -o addr show dev "$bridge")" ]] || { echo "Service bridge is not addressless" >&2; exit 1; }
    bridge_mappings="$bridge_mappings,$physnet:$bridge"
  done <<< "$extra_bridges"
fi
# END operator-selected addressless VLAN bridges
{{- end }}
