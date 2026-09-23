from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def load(relative):
    return yaml.safe_load((ROOT / relative).read_text())


def test_mariadb_uses_dedicated_rack_spread_database_pool():
    values = load("deploy/values/site/mariadb.yaml")
    assert values["labels"]["server"] == {
        "node_selector_key": "openstack-database",
        "node_selector_value": "enabled",
    }
    anti = values["pod"]["affinity"]["anti"]
    assert anti["type"]["default"] == "requiredDuringSchedulingIgnoredDuringExecution"
    assert anti["topologyKey"]["default"] == "topology.kubernetes.io/zone"
    assert values["pod"]["replicas"]["server"] == 3


def test_openstack_exporter_is_three_replica_controller_workload():
    for relative in (
        "deploy/values/site/prometheus-openstack-exporter.yaml",
        "deploy/monitoring/values/openstack-exporter.yaml",
    ):
        values = load(relative)
        assert values["labels"]["openstack_exporter"] == {
            "node_selector_key": "openstack-control-plane",
            "node_selector_value": "enabled",
        }
        assert values["pod"]["replicas"]["prometheus_openstack_exporter"] == 3
        anti = values["pod"]["affinity"]["anti"]
        assert anti["type"]["default"] == "requiredDuringSchedulingIgnoredDuringExecution"
        assert anti["topologyKey"]["default"] == "topology.kubernetes.io/zone"


def test_ovn_databases_follow_their_retained_local_pvs():
    values = load("deploy/values/site/ovn.yaml")
    expected = {
        "node_selector_key": "openstack-ovn-database",
        "node_selector_value": "enabled",
    }
    assert values["labels"]["ovn_ovsdb_nb"] == expected
    assert values["labels"]["ovn_ovsdb_sb"] == expected
    assert values["labels"]["ovn_northd"] == {
        "node_selector_key": "openstack-control-plane",
        "node_selector_value": "enabled",
    }
