#!/usr/bin/env python3
"""Create and verify the persistent Octavia OVN PoC load balancer.

Authentication is read from the standard OS_* environment variables.  The
script prints resource identifiers and HTTP responses, but never credentials
or the Keystone token.
"""

import json
import subprocess
import time
import urllib.error
import urllib.request


LB_NAME = "octavia-e2e-lb"
LISTENER_NAME = "octavia-e2e-http"
POOL_NAME = "octavia-e2e-pool"
SUBNET_NAME = "poc-egress-subnet"
EXTERNAL_NETWORK = "public"
BACKENDS = ("octavia-backend-1", "octavia-backend-2")


def osc(*args):
    return subprocess.check_output(
        ["openstack", *args, "-f", "json"], text=True
    ).strip()


def osc_json(*args):
    output = osc(*args)
    return json.loads(output) if output else {}


TOKEN = subprocess.check_output(
    ["openstack", "token", "issue", "-f", "value", "-c", "id"], text=True
).strip()
ENDPOINT = subprocess.check_output(
    [
        "openstack",
        "endpoint",
        "list",
        "--service",
        "octavia",
        "--interface",
        "internal",
        "-f",
        "value",
        "-c",
        "URL",
    ],
    text=True,
).splitlines()[0].rstrip("/")


def request(method, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        ENDPOINT + path,
        data=data,
        method=method,
        headers={"X-Auth-Token": TOKEN, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        payload = response.read()
    return json.loads(payload) if payload else {}


def find(collection, name):
    for item in request("GET", f"/v2/lbaas/{collection}")[collection]:
        if item["name"] == name:
            return item
    return None


def wait_active(collection, resource_id, timeout=300):
    singular = {
        "loadbalancers": "loadbalancer",
        "listeners": "listener",
        "pools": "pool",
        "members": "member",
    }[collection]
    deadline = time.time() + timeout
    while time.time() < deadline:
        item = request("GET", f"/v2/lbaas/{collection}/{resource_id}")[singular]
        status = item.get("provisioning_status")
        if status == "ACTIVE":
            return item
        if status == "ERROR":
            raise RuntimeError(f"{singular} {resource_id} entered ERROR")
        time.sleep(3)
    raise TimeoutError(f"{singular} {resource_id} did not become ACTIVE")


def wait_member(pool_id, member_id, timeout=300):
    deadline = time.time() + timeout
    while time.time() < deadline:
        member = request(
            "GET", f"/v2/lbaas/pools/{pool_id}/members/{member_id}"
        )["member"]
        status = member.get("provisioning_status")
        if status == "ACTIVE":
            return member
        if status == "ERROR":
            raise RuntimeError(f"member {member_id} entered ERROR")
        time.sleep(3)
    raise TimeoutError(f"member {member_id} did not become ACTIVE")


subnet_id = osc_json("subnet", "show", SUBNET_NAME)["id"]

lb = find("loadbalancers", LB_NAME)
if lb is None:
    lb = request(
        "POST",
        "/v2/lbaas/loadbalancers",
        {
            "loadbalancer": {
                "name": LB_NAME,
                "vip_subnet_id": subnet_id,
                "provider": "ovn",
            }
        },
    )["loadbalancer"]
lb = wait_active("loadbalancers", lb["id"])

listener = find("listeners", LISTENER_NAME)
if listener is None:
    listener = request(
        "POST",
        "/v2/lbaas/listeners",
        {
            "listener": {
                "name": LISTENER_NAME,
                "protocol": "TCP",
                "protocol_port": 80,
                "loadbalancer_id": lb["id"],
            }
        },
    )["listener"]
listener = wait_active("listeners", listener["id"])
wait_active("loadbalancers", lb["id"])

pool = find("pools", POOL_NAME)
if pool is None:
    pool = request(
        "POST",
        "/v2/lbaas/pools",
        {
            "pool": {
                "name": POOL_NAME,
                "protocol": "TCP",
                "lb_algorithm": "SOURCE_IP_PORT",
                "listener_id": listener["id"],
            }
        },
    )["pool"]
pool = wait_active("pools", pool["id"])
wait_active("loadbalancers", lb["id"])

existing_members = {
    member["name"]: member
    for member in request("GET", f"/v2/lbaas/pools/{pool['id']}/members")[
        "members"
    ]
}
for backend in BACKENDS:
    addresses = osc_json("server", "show", backend)["addresses"]
    if isinstance(addresses, dict):
        network_addresses = next(iter(addresses.values()))
        address = network_addresses[0] if isinstance(network_addresses, list) else network_addresses
    else:
        address = addresses.split("=")[-1].split(",")[0].strip()
    member = existing_members.get(backend)
    if member is None:
        member = request(
            "POST",
            f"/v2/lbaas/pools/{pool['id']}/members",
            {
                "member": {
                    "name": backend,
                    "address": address,
                    "protocol_port": 80,
                    "subnet_id": subnet_id,
                }
            },
        )["member"]
    wait_member(pool["id"], member["id"])
    wait_active("loadbalancers", lb["id"])

floating_ips = json.loads(osc("floating", "ip", "list"))
fip = next(
    (item for item in floating_ips if item.get("Port") == lb["vip_port_id"]),
    None,
)
if fip is None:
    fip = osc_json("floating", "ip", "create", EXTERNAL_NETWORK)
    subprocess.check_call(
        ["openstack", "floating", "ip", "set", "--port", lb["vip_port_id"], fip["id"]]
    )

floating_address = fip.get("Floating IP Address") or fip["floating_ip_address"]
responses = []
for _ in range(8):
    with urllib.request.urlopen(f"http://{floating_address}/", timeout=15) as response:
        responses.append(response.read().decode().strip())

print(
    json.dumps(
        {
            "loadbalancer_id": lb["id"],
            "provider": lb["provider"],
            "vip_address": lb["vip_address"],
            "vip_port_id": lb["vip_port_id"],
            "floating_ip": floating_address,
            "listener_id": listener["id"],
            "pool_id": pool["id"],
            "http_responses": responses,
        },
        indent=2,
    )
)
