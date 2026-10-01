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


def test_openstack_exporter_installs_the_locked_patched_chart():
    installer = (ROOT / "deploy/monitoring/scripts/install.sh").read_text()
    expected = "helm/packages/patched/prometheus-openstack-exporter-2026.1.0.tgz"
    assert expected in installer
    assert "helm/packages/upstream/prometheus-openstack-exporter" not in installer

    release_lock = load("release-lock.yaml")
    locked = next(
        chart
        for chart in release_lock["spec"]["releases"]
        if chart["name"] == "prometheus-openstack-exporter"
    )
    assert locked["package"] == expected


def test_openstack_exporter_tls_override_is_renderable_by_patched_chart():
    for relative in (
        "deploy/values/site/prometheus-openstack-exporter.yaml",
        "deploy/monitoring/values/openstack-exporter.yaml",
    ):
        values = load(relative)
        assert values["conf"]["prometheus_openstack_exporter"]["verify"] is False
        assert "--endpoint-type=internal" in values["conf"]["prometheus_openstack_exporter"]["extra_args"]
