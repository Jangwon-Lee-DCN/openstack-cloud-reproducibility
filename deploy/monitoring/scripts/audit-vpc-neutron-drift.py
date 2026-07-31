#!/usr/bin/env python3
"""Read-only per-project CR/Neutron drift audit for the scheduled Job."""
import json
import os
import ssl
import subprocess
import time
import urllib.request

NAMESPACE = os.environ["PROJECT_NAMESPACE"]
API = "https://kubernetes.default.svc"
TOKEN = open("/var/run/secrets/kubernetes.io/serviceaccount/token").read()
CA = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"


def kube(resource):
    url = f"{API}/apis/vpc.dcn.ssu.ac.kr/v1alpha1/namespaces/{NAMESPACE}/{resource}"
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}"})
    with urllib.request.urlopen(request, context=ssl.create_default_context(cafile=CA)) as response:
        return json.load(response)["items"]


def osc(*args):
    output = subprocess.check_output(["openstack", "--os-cloud", "openstack", *args, "-f", "json"], text=True)
    return json.loads(output)


def row_id(row):
    return row.get("ID") or row.get("Id") or row.get("id")


def field(row, *names):
    for name in names:
        if name in row:
            return row[name]
    return None


def normalized_gateway(value):
    if not isinstance(value, dict):
        return {}
    fixed_ips = value.get("external_fixed_ips") or []
    return {
        "networkID": value.get("network_id"),
        "enableSNAT": value.get("enable_snat"),
        "fixedIPs": sorted(
            item.get("ip_address") for item in fixed_ips if isinstance(item, dict) and item.get("ip_address")
        ),
    }


def tags(row):
    value = field(row, "Tags", "tags") or []
    if isinstance(value, str):
        value = [item.strip() for item in value.split(",") if item.strip()]
    return set(value)


def ownership_tag_drift(items, actual_by_id, status_key):
    missing = []
    for item in items:
        neutron_id = item.get("status", {}).get(status_key)
        actual = actual_by_id.get(neutron_id)
        if not neutron_id or actual is None:
            continue
        required = {
            "vpc-control-plane",
            "vpc-cr-uid=" + item.get("metadata", {}).get("uid", ""),
        }
        if not required.issubset(tags(actual)):
            missing.append({
                "id": neutron_id,
                "kind": item.get("kind"),
                "name": item.get("metadata", {}).get("name"),
                "missingTags": sorted(required - tags(actual)),
            })
    return missing


security_groups, elastic_ips, nat_gateways = kube("securitygroups"), kube("elasticips"), kube("natgateways")
actual_sg, actual_fip, actual_router = osc("security", "group", "list"), osc("floating", "ip", "list"), osc("router", "list")
actual_rules = osc("security", "group", "rule", "list")

desired_sg = {x.get("status", {}).get("securityGroupID") for x in security_groups} - {None}
desired_fip = {x.get("status", {}).get("floatingIPID") for x in elastic_ips} - {None}
desired_router = {x.get("status", {}).get("routerID") for x in nat_gateways} - {None}
actual_sg_ids, actual_fip_ids, actual_router_ids = map(lambda rows: {row_id(x) for x in rows}, (actual_sg, actual_fip, actual_router))

desired_rule_ids = {
    neutron_id
    for group in security_groups
    for neutron_id in group.get("status", {}).get("ruleIDs", {}).values()
}
actual_rule_ids = {row_id(x) for x in actual_rules}

fip_association_drift, fip_fixed_ip_drift = [], []
actual_fip_by_id = {row_id(x): x for x in actual_fip}
actual_sg_by_id = {row_id(x): x for x in actual_sg}
actual_router_by_id = {row_id(x): x for x in actual_router}
for item in elastic_ips:
    status = item.get("status", {})
    actual = actual_fip_by_id.get(status.get("floatingIPID"), {})
    actual_port = field(actual, "Port", "port_id") or None
    if status.get("floatingIPID") and actual_port != status.get("targetPortID"):
        fip_association_drift.append(status["floatingIPID"])
    expected_fixed_ip = status.get("targetPrivateIPAddress")
    actual_fixed_ip = field(actual, "Fixed IP Address", "fixed_ip_address") or None
    if status.get("floatingIPID") and expected_fixed_ip and actual_fixed_ip != expected_fixed_ip:
        fip_fixed_ip_drift.append(status["floatingIPID"])

router_gateway_drift = []
for item in nat_gateways:
    status = item.get("status", {})
    router_id = status.get("routerID")
    if not router_id or router_id not in actual_router_ids:
        continue
    router = osc("router", "show", router_id)
    actual_gateway = normalized_gateway(field(router, "external_gateway_info", "External gateway info"))
    expected_network = status.get("externalNetworkID")
    expected_fixed_ips = sorted(status.get("externalFixedIPs") or [])
    if (
        (expected_network and actual_gateway.get("networkID") != expected_network)
        or actual_gateway.get("enableSNAT") is not True
        or (expected_fixed_ips and actual_gateway.get("fixedIPs") != expected_fixed_ips)
    ):
        router_gateway_drift.append({
            "routerID": router_id,
            "expected": {
                "networkID": expected_network,
                "enableSNAT": True,
                "fixedIPs": expected_fixed_ips,
            },
            "actual": actual_gateway,
        })

report = {
    "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "mode": "read-only",
    "missingActual": {
        "securityGroups": sorted(desired_sg - actual_sg_ids),
        "securityGroupRules": sorted(desired_rule_ids - actual_rule_ids),
        "floatingIPs": sorted(desired_fip - actual_fip_ids),
        "routers": sorted(desired_router - actual_router_ids),
    },
    "untrackedManaged": {
        "securityGroups": sorted({
            row_id(x) for x in actual_sg if "vpc-control-plane" in (x.get("Description") or "")
        } - desired_sg),
        "floatingIPs": sorted({
            row_id(x) for x in actual_fip if "vpc-control-plane" in (x.get("Description") or "")
        } - desired_fip),
        "routers": sorted({
            row_id(x) for x in actual_router if "vpc-control-plane" in (x.get("Description") or "")
        } - desired_router),
    },
    "associationDrift": {
        "floatingIPPorts": sorted(fip_association_drift),
        "floatingIPFixedIPs": sorted(fip_fixed_ip_drift),
        "routerGateways": router_gateway_drift,
    },
    "ownershipTagDrift": [
        *ownership_tag_drift(security_groups, actual_sg_by_id, "securityGroupID"),
        *ownership_tag_drift(elastic_ips, actual_fip_by_id, "floatingIPID"),
        *ownership_tag_drift(nat_gateways, actual_router_by_id, "routerID"),
    ],
}
report["summary"] = {
    "missingActual": sum(map(len, report["missingActual"].values())),
    "untrackedManaged": sum(map(len, report["untrackedManaged"].values())),
    "associationDrift": len(fip_association_drift) + len(fip_fixed_ip_drift) + len(router_gateway_drift),
    "ownershipTagDrift": len(report["ownershipTagDrift"]),
}
print(json.dumps(report, sort_keys=True))

pushgateway = os.environ.get("PUSHGATEWAY_URL")
if pushgateway:
    lines = [
        "# TYPE vpc_neutron_drift_resources gauge",
        *[
            f'vpc_neutron_drift_resources{{project_namespace="{NAMESPACE}",type="{kind}"}} {value}'
            for kind, value in report["summary"].items()
        ],
        "# TYPE vpc_neutron_drift_last_success_timestamp_seconds gauge",
        f'vpc_neutron_drift_last_success_timestamp_seconds{{project_namespace="{NAMESPACE}"}} {int(time.time())}',
    ]
    request = urllib.request.Request(
        f"{pushgateway.rstrip('/')}/metrics/job/vpc-neutron-drift/project_namespace/{NAMESPACE}",
        data=("\n".join(lines) + "\n").encode(),
        method="PUT",
    )
    urllib.request.urlopen(request, timeout=10).read()
