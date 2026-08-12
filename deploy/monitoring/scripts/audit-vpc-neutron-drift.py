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
internet_gateways, load_balancers, vpc_endpoints = kube("internetgateways"), kube("loadbalancers"), kube("vpcendpoints")
private_dns_zones, flow_logs = kube("privatednszones"), kube("flowlogconfigs")
network_interfaces = kube("networkinterfaces")
actual_sg, actual_fip, actual_router = osc("security", "group", "list"), osc("floating", "ip", "list"), osc("router", "list")
actual_rules = osc("security", "group", "rule", "list")
actual_lbs, actual_ports = osc("loadbalancer", "list"), osc("port", "list")
actual_zones, actual_logs = osc("zone", "list"), osc("network", "log", "list")

desired_sg = {x.get("status", {}).get("securityGroupID") for x in security_groups} - {None}
desired_fip = {x.get("status", {}).get("floatingIPID") for x in elastic_ips} - {None}
desired_router = {x.get("status", {}).get("routerID") for x in nat_gateways} - {None}
desired_igw_router = {x.get("status", {}).get("routerID") for x in internet_gateways} - {None}
desired_lb = {x.get("status", {}).get("loadBalancerID") for x in load_balancers} - {None}
desired_endpoint_ports = {
    port_id for endpoint in vpc_endpoints for port_id in endpoint.get("status", {}).get("endpointPortIDs", [])
}
desired_eni_ports = {x.get("status", {}).get("portID") for x in network_interfaces} - {None}
desired_zone = {x.get("status", {}).get("zoneID") for x in private_dns_zones} - {None}
desired_log = {
    log_id
    for item in flow_logs
    for log_id in (item.get("status", {}).get("logIDs") or [item.get("status", {}).get("logID")])
    if log_id
}
actual_sg_ids, actual_fip_ids, actual_router_ids = map(lambda rows: {row_id(x) for x in rows}, (actual_sg, actual_fip, actual_router))
actual_lb_ids, actual_port_ids = {row_id(x) for x in actual_lbs}, {row_id(x) for x in actual_ports}
actual_zone_ids, actual_log_ids = {row_id(x) for x in actual_zones}, {row_id(x) for x in actual_logs}

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
actual_port_by_id = {row_id(x): x for x in actual_ports}
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
for gateway_kind, item in [
    *(("NatGateway", item) for item in nat_gateways),
    *(("InternetGateway", item) for item in internet_gateways),
]:
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
        or (gateway_kind == "NatGateway" and actual_gateway.get("enableSNAT") is not True)
        or (expected_fixed_ips and actual_gateway.get("fixedIPs") != expected_fixed_ips)
    ):
        router_gateway_drift.append({
            "routerID": router_id,
            "expected": {
                "networkID": expected_network,
                "enableSNAT": True if gateway_kind == "NatGateway" else actual_gateway.get("enableSNAT"),
                "fixedIPs": expected_fixed_ips,
            },
            "kind": gateway_kind,
            "actual": actual_gateway,
        })

flow_log_drift = []
actual_log_by_id = {row_id(x): x for x in actual_logs}
for item in flow_logs:
    spec, status = item.get("spec", {}), item.get("status", {})
    log_ids = status.get("logIDs") or ([status.get("logID")] if status.get("logID") else [])
    sg_ids = status.get("securityGroupIDs") or ([status.get("securityGroupID")] if status.get("securityGroupID") else [])
    for log_id, sg_id in zip(log_ids, sg_ids):
        actual = actual_log_by_id.get(log_id)
        if actual is None:
            continue
        actual_enabled = field(actual, "Enabled", "enabled")
        if isinstance(actual_enabled, str):
            actual_enabled = actual_enabled.lower() == "true"
        expected = {
            "resourceID": sg_id,
            "event": spec.get("event") or "ALL",
            "enabled": bool(spec.get("enabled", True)),
        }
        observed = {
            "resourceID": field(actual, "Resource ID", "resource_id"),
            "event": field(actual, "Event", "event"),
            "enabled": actual_enabled,
        }
        if expected != observed:
            flow_log_drift.append({"logID": log_id, "expected": expected, "actual": observed})


def normalized_records(value):
    if isinstance(value, list):
        return sorted(str(record) for record in value)
    if isinstance(value, str):
        value = value.strip()
        if value.startswith("["):
            try:
                decoded = json.loads(value.replace("'", '"'))
                if isinstance(decoded, list):
                    return sorted(str(record) for record in decoded)
            except json.JSONDecodeError:
                pass
        return [value] if value else []
    return []


dns_record_drift = []
for item in private_dns_zones:
    zone_id = item.get("status", {}).get("zoneID")
    if not zone_id or zone_id not in actual_zone_ids:
        continue
    actual_recordsets = osc("recordset", "list", zone_id)
    actual_by_key = {
        (field(row, "Name", "name"), field(row, "Type", "type")): row
        for row in actual_recordsets
        if field(row, "Type", "type") not in {"NS", "SOA"}
    }
    desired_by_key = {
        (record.get("name"), record.get("type")): record
        for record in item.get("spec", {}).get("records", [])
    }
    missing = sorted(["/".join(key) for key in desired_by_key.keys() - actual_by_key.keys()])
    extra = sorted(["/".join(key) for key in actual_by_key.keys() - desired_by_key.keys()])
    changed = []
    for key in desired_by_key.keys() & actual_by_key.keys():
        desired_record, actual_record = desired_by_key[key], actual_by_key[key]
        desired_ttl = desired_record.get("ttlSeconds") or item.get("spec", {}).get("ttlSeconds") or 3600
        actual_ttl = field(actual_record, "TTL", "ttl")
        if normalized_records(field(actual_record, "Records", "records")) != sorted(desired_record.get("records", [])) or actual_ttl is None or int(actual_ttl) != int(desired_ttl):
            changed.append("/".join(key))
    if missing or extra or changed:
        dns_record_drift.append({"zoneID": zone_id, "missing": missing, "extra": extra, "changed": sorted(changed)})

endpoint_port_tag_drift = []
for endpoint in vpc_endpoints:
    required = {"vpc-control-plane", "vpc-cr-uid=" + endpoint.get("metadata", {}).get("uid", "")}
    for port_id in endpoint.get("status", {}).get("endpointPortIDs", []):
        actual = actual_port_by_id.get(port_id)
        if actual is not None and not required.issubset(tags(actual)):
            endpoint_port_tag_drift.append({
                "id": port_id,
                "kind": "VpcEndpoint",
                "name": endpoint.get("metadata", {}).get("name"),
                "missingTags": sorted(required - tags(actual)),
            })

report = {
    "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "mode": "read-only",
    "missingActual": {
        "securityGroups": sorted(desired_sg - actual_sg_ids),
        "securityGroupRules": sorted(desired_rule_ids - actual_rule_ids),
        "floatingIPs": sorted(desired_fip - actual_fip_ids),
        "routers": sorted(desired_router - actual_router_ids),
        "internetGatewayRouters": sorted(desired_igw_router - actual_router_ids),
        "loadBalancers": sorted(desired_lb - actual_lb_ids),
        "endpointPorts": sorted(desired_endpoint_ports - actual_port_ids),
        "networkInterfacePorts": sorted(desired_eni_ports - actual_port_ids),
        "privateDnsZones": sorted(desired_zone - actual_zone_ids),
        "flowLogs": sorted(desired_log - actual_log_ids),
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
        } - desired_router - desired_igw_router),
        "loadBalancers": sorted({
            row_id(x) for x in actual_lbs if "vpc-control-plane" in (x.get("Description") or "")
        } - desired_lb),
        "endpointPorts": sorted({
            row_id(x) for x in actual_ports if "vpc-control-plane interface endpoint" in (x.get("Description") or "")
        } - desired_endpoint_ports),
        "networkInterfacePorts": sorted({
            row_id(x) for x in actual_ports if (field(x, "Name", "name") or "").startswith("vpc-ni-")
        } - desired_eni_ports),
        "privateDnsZones": sorted({
            row_id(x) for x in actual_zones if "vpc-control-plane PrivateDnsZone" in (field(x, "Description", "description") or "")
        } - desired_zone),
        "flowLogs": sorted({
            row_id(x) for x in actual_logs if (field(x, "Name", "name") or "").startswith(NAMESPACE + "-")
        } - desired_log),
    },
    "associationDrift": {
        "floatingIPPorts": sorted(fip_association_drift),
        "floatingIPFixedIPs": sorted(fip_fixed_ip_drift),
        "routerGateways": router_gateway_drift,
        "flowLogs": flow_log_drift,
        "privateDnsRecords": dns_record_drift,
    },
    "ownershipTagDrift": [
        *ownership_tag_drift(security_groups, actual_sg_by_id, "securityGroupID"),
        *ownership_tag_drift(elastic_ips, actual_fip_by_id, "floatingIPID"),
        *ownership_tag_drift(nat_gateways, actual_router_by_id, "routerID"),
        *ownership_tag_drift(network_interfaces, actual_port_by_id, "portID"),
        *endpoint_port_tag_drift,
    ],
}
report["summary"] = {
    "missingActual": sum(map(len, report["missingActual"].values())),
    "untrackedManaged": sum(map(len, report["untrackedManaged"].values())),
    "associationDrift": len(fip_association_drift) + len(fip_fixed_ip_drift) + len(router_gateway_drift) + len(flow_log_drift) + len(dns_record_drift),
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
