#!/usr/bin/env bash
set -euo pipefail

action=${1:?missing action}
prefix=rebuild-lab
network=${prefix}-net
provider_network=${prefix}-provider-net
subnet=${prefix}-subnet
router=${prefix}-router
security_group=${prefix}-sg
keypair=${prefix}-key
flavor=${prefix}-medium
image_name=ubuntu-24.04-rebuild-lab
image_file=ubuntu-24.04-server-cloudimg-amd64.img
api_vip=10.77.0.250
base_url=${UBUNTU_IMAGE_BASE_URL%/}

wait_server() {
  local server=$1 status
  for _ in $(seq 1 120); do
    status=$(openstack server show "$server" -f value -c status)
    [[ "$status" == ACTIVE ]] && return 0
    [[ "$status" == ERROR ]] && {
      openstack server show "$server"
      return 1
    }
    sleep 5
  done
  return 1
}

create_lab() {
  if ! openstack image show "$image_name" >/dev/null 2>&1; then
    work=$(mktemp -d /tmp/rebuild-lab-image.XXXXXX)
    trap 'rm -rf -- "$work"' RETURN
    curl -fsSLo "$work/SHA256SUMS" "$base_url/SHA256SUMS"
    curl -fL --retry 5 --retry-delay 3 \
      -o "$work/$image_file" "$base_url/$image_file"
    expected=$(awk -v file="*$image_file" '$2 == file || $2 == substr(file, 2) {print $1}' \
      "$work/SHA256SUMS")
    test -n "$expected"
    printf '%s  %s\n' "$expected" "$work/$image_file" | sha256sum -c -
    openstack image create "$image_name" --file "$work/$image_file" \
      --disk-format qcow2 --container-format bare --private \
      --property os_distro=ubuntu --property os_version=24.04 \
      --property hw_qemu_guest_agent=yes >/dev/null
  fi

  openstack flavor show "$flavor" >/dev/null 2>&1 || \
    openstack flavor create "$flavor" --vcpus 2 --ram 8192 --disk 40 >/dev/null

  if ! openstack keypair show "$keypair" >/dev/null 2>&1; then
    test -n "${LAB_PUBLIC_KEY:-}"
    key_file=$(mktemp /tmp/rebuild-lab-key.XXXXXX)
    printf '%s\n' "$LAB_PUBLIC_KEY" > "$key_file"
    openstack keypair create "$keypair" --public-key "$key_file" >/dev/null
    rm -f -- "$key_file"
  fi

  openstack network show "$network" >/dev/null 2>&1 || \
    openstack network create "$network" >/dev/null
  openstack network show "$provider_network" >/dev/null 2>&1 || \
    openstack network create "$provider_network" --disable-port-security >/dev/null
  openstack subnet show "$subnet" >/dev/null 2>&1 || \
    openstack subnet create "$subnet" --network "$network" \
      --subnet-range 10.77.0.0/24 --gateway 10.77.0.1 \
      --dns-nameserver 1.1.1.1 >/dev/null
  if ! openstack port show "${prefix}-api-vip-reservation" >/dev/null 2>&1; then
    openstack port create "${prefix}-api-vip-reservation" --network "$network" \
      --fixed-ip "subnet=$subnet,ip-address=$api_vip" --disable >/dev/null
  fi
  openstack router show "$router" >/dev/null 2>&1 || \
    openstack router create "$router" >/dev/null
  openstack router set "$router" --external-gateway public
  openstack router add subnet "$router" "$subnet" 2>/dev/null || true

  if ! openstack security group show "$security_group" >/dev/null 2>&1; then
    openstack security group create "$security_group" >/dev/null
    openstack security group rule create "$security_group" \
      --ingress --ethertype IPv4 --protocol icmp >/dev/null
    openstack security group rule create "$security_group" \
      --ingress --ethertype IPv4 --protocol tcp --dst-port 22 \
      --remote-ip 192.168.21.0/24 >/dev/null
    openstack security group rule create "$security_group" \
      --ingress --ethertype IPv4 --remote-group "$security_group" >/dev/null
  fi

  for index in 0 1 2; do
    server=${prefix}-${index}
    if ! openstack server show "$server" >/dev/null 2>&1; then
      openstack server create "$server" --image "$image_name" \
        --flavor "$flavor" --network "$network" --key-name "$keypair" \
        --security-group "$security_group" --config-drive true >/dev/null
    fi
    wait_server "$server"
    management_port=$(openstack port list --server "$server" --network "$network" \
      -f value -c ID | head -1)
    if ! openstack port show "$management_port" -f json -c allowed_address_pairs | \
      grep -q "$api_vip"; then
      openstack port set "$management_port" \
        --allowed-address "ip-address=$api_vip"
    fi
    provider_port=${prefix}-provider-port-${index}
    if ! openstack port show "$provider_port" >/dev/null 2>&1; then
      openstack port create "$provider_port" --network "$provider_network" \
        --disable-port-security >/dev/null
      openstack server add port "$server" "$provider_port"
    fi
    has_floating_ip=0
    while read -r port_id; do
      if [[ -n "$port_id" ]] && \
        openstack floating ip list --port "$port_id" -f value -c ID | grep -q .; then
        has_floating_ip=1
      fi
    done < <(openstack port list --server "$server" -f value -c ID)
    if [[ "$has_floating_ip" == 0 ]]; then
      floating_ip=$(openstack floating ip create public -f value -c floating_ip_address)
      openstack server add floating ip "$server" "$floating_ip"
    fi
  done
  status_lab
}

status_lab() {
  openstack server list --name "^${prefix}-[0-2]$" --name-lookup-one-by-one \
    -c Name -c Status -c Networks -c Flavor -f table
  openstack hypervisor stats show -f yaml
}

destroy_lab() {
  for index in 0 1 2; do
    server=${prefix}-${index}
    if openstack server show "$server" >/dev/null 2>&1; then
      while read -r address; do
        [[ -n "$address" ]] && openstack floating ip delete "$address"
      done < <(openstack floating ip list --server "$server" -f value \
        -c 'Floating IP Address')
      openstack server delete --wait "$server"
    fi
    openstack port delete "${prefix}-provider-port-${index}" 2>/dev/null || true
  done
  openstack router remove subnet "$router" "$subnet" 2>/dev/null || true
  openstack router delete "$router" 2>/dev/null || true
  openstack port delete "${prefix}-api-vip-reservation" 2>/dev/null || true
  openstack subnet delete "$subnet" 2>/dev/null || true
  openstack network delete "$network" 2>/dev/null || true
  openstack network delete "$provider_network" 2>/dev/null || true
  openstack security group delete "$security_group" 2>/dev/null || true
  openstack keypair delete "$keypair" 2>/dev/null || true
  openstack flavor delete "$flavor" 2>/dev/null || true
  if [[ ${DELETE_LAB_IMAGE:-0} == 1 ]]; then
    openstack image delete "$image_name" 2>/dev/null || true
  fi
}

case "$action" in
  create) create_lab ;;
  status) status_lab ;;
  destroy) destroy_lab ;;
  *) echo "unsupported action: $action" >&2; exit 2 ;;
esac
