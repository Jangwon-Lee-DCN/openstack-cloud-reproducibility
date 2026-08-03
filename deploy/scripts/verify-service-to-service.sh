#!/usr/bin/env bash
set -euo pipefail

namespace=${NAMESPACE:-openstack}
pod=${SERVICE_REGRESSION_POD:-service-regression-client}
image=${OPENSTACK_CLIENT_IMAGE:-quay.io/airshipit/openstack-client:2026.1-ubuntu_noble}

cleanup_pod() {
  kubectl -n "${namespace}" delete pod "${pod}" --ignore-not-found --wait=false >/dev/null 2>&1 || true
}
trap cleanup_pod EXIT
cleanup_pod

overrides=$(jq -nc --arg image "${image}" '{spec:{containers:[{
  name:"service-regression-client", image:$image, command:["sleep","1800"],
  envFrom:[{secretRef:{name:"keystone-keystone-admin"}}]
}]}}')
kubectl -n "${namespace}" run "${pod}" --image="${image}" --restart=Never \
  --overrides="${overrides}" \
  -- sleep 1800 >/dev/null
kubectl -n "${namespace}" wait --for=condition=Ready "pod/${pod}" --timeout=90s >/dev/null

kubectl -n "${namespace}" exec -i "${pod}" -- bash -s <<'INNER'
set -euo pipefail
suffix=$(date +%s)
net=s2s-net-$suffix; subnet=s2s-subnet-$suffix; router=s2s-router-$suffix
server=s2s-vm-$suffix; volume=s2s-volume-$suffix; lb=s2s-amphora-$suffix
secret=s2s-secret-$suffix; zone=s2s-$suffix.cloud.dcn.ssu.ac.kr.
network_id= subnet_id= router_id= server_id= volume_id= lb_id= secret_href=

cleanup_resources() {
  set +e
  [ -z "$lb_id" ] || openstack loadbalancer delete --cascade "$lb_id" >/dev/null 2>&1
  [ -z "$server_id" ] || openstack server remove volume "$server_id" "$volume_id" >/dev/null 2>&1
  [ -z "$server_id" ] || openstack server delete "$server_id" >/dev/null 2>&1
  for attempt in $(seq 1 60); do
    [ -z "$server_id" ] || ! openstack server show "$server_id" >/dev/null 2>&1 && break
    sleep 2
  done
  [ -z "$volume_id" ] || openstack volume delete "$volume_id" >/dev/null 2>&1
  openstack zone delete "$zone" >/dev/null 2>&1
  [ -z "$secret_href" ] || openstack secret delete "$secret_href" >/dev/null 2>&1
  [ -z "$router_id" ] || [ -z "$subnet_id" ] || openstack router remove subnet "$router_id" "$subnet_id" >/dev/null 2>&1
  [ -z "$router_id" ] || openstack router delete "$router_id" >/dev/null 2>&1
  [ -z "$network_id" ] || openstack network delete "$network_id" >/dev/null 2>&1
}
trap cleanup_resources EXIT

wait_field() {
  resource=$1; id=$2; field=$3; wanted=$4; limit=$5
  for attempt in $(seq 1 "$limit"); do
    value=$(openstack "$resource" show "$id" -f value -c "$field" 2>/dev/null || true)
    echo "$resource $id attempt=$attempt $field=$value"
    [ "$value" = "$wanted" ] && return 0
    [ "$value" = ERROR ] && return 1
    sleep 3
  done
  return 1
}

openstack token issue >/dev/null
network_id=$(openstack network create "$net" -f value -c id)
subnet_id=$(openstack subnet create "$subnet" --network "$network_id" \
  --subnet-range 10.253.0.0/24 --dns-nameserver 192.168.21.10 -f value -c id)
router_id=$(openstack router create "$router" -f value -c id)
openstack router set "$router_id" --external-gateway public
openstack router add subnet "$router_id" "$subnet_id"
echo 'PASS Keystone -> Neutron: disposable network topology created'

server_id=$(openstack server create "$server" --image 'Cirros 0.6.2 64-bit' \
  --flavor m1.small --network "$network_id" -f value -c id)
wait_field server "$server_id" status ACTIVE 100
[ "$(openstack port list --server "$server_id" -f value -c Status | head -1)" = ACTIVE ]
echo 'PASS Nova -> Glance/Neutron: server ACTIVE with bound Neutron port'

volume_id=$(openstack volume create "$volume" --size 1 -f value -c id)
wait_field volume "$volume_id" status available 100
openstack server add volume "$server_id" "$volume_id"
wait_field volume "$volume_id" status in-use 100
openstack volume show "$volume_id" -f json -c attachments | grep -q "$server_id"
echo 'PASS Nova <-> Cinder: RBD volume attached and in-use'

secret_href=$(openstack secret store --name "$secret" \
  --payload service-regression-value -f value -c 'Secret href')
[ "$(openstack secret get "$secret_href" -f value -c Status)" = ACTIVE ]
echo 'PASS Keystone -> Barbican: secret CRUD authentication path works'

openstack zone create --email hostmaster@dcn.ssu.ac.kr "$zone" >/dev/null
wait_field zone "$zone" status ACTIVE 60
echo 'PASS Designate -> PowerDNS: zone reached ACTIVE'

lb_id=$(openstack loadbalancer create --name "$lb" --provider amphora \
  --vip-subnet-id "$subnet_id" -f value -c id)
wait_field loadbalancer "$lb_id" provisioning_status ACTIVE 200
[ "$(openstack server list --all-projects --name amphora -f value -c ID | wc -l)" -ge 1 ]
echo 'PASS Octavia -> Glance/Nova/Neutron: Amphora load balancer ACTIVE'
echo 'PASS service-to-service disposable workload matrix completed; cleanup follows'
INNER

echo 'PASS service-to-service regression completed and disposable client removed'
