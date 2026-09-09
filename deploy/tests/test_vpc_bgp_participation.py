from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_vpc_preflight_filters_explicit_non_participants():
    script = (ROOT / "deploy/scripts/preflight-vpc-p0-p1-acceptance.sh").read_text()

    assert 'host.get("ovn_bgp_participation", True)' in script
    assert 'all("ovn_gateway" in host.get("node_roles", []) for host in participants)' in script
    assert 'set(host["rack"] for host in participants) == set(racks)' in script
    assert 'host["node_ip"]' in script and 'for host in participants' in script


def test_explicit_gpu_exception_keeps_qualified_rack_coverage():
    computes = [
        {"rack": "rack-1", "node_ip": "10.64.20.21", "node_roles": ["compute", "ovn_gateway"]},
        {"rack": "rack-1", "node_ip": "10.64.20.23", "node_roles": ["compute", "gpu"], "ovn_bgp_participation": False},
        {"rack": "rack-2", "node_ip": "10.65.20.21", "node_roles": ["compute", "ovn_gateway"]},
        {"rack": "rack-3", "node_ip": "10.66.20.21", "node_roles": ["compute", "ovn_gateway"]},
    ]

    participants = [host for host in computes if host.get("ovn_bgp_participation", True)]

    assert all("ovn_gateway" in host["node_roles"] for host in participants)
    assert {host["rack"] for host in participants} == {"rack-1", "rack-2", "rack-3"}
    assert "10.64.20.23" not in {host["node_ip"] for host in participants}
