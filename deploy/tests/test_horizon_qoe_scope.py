from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_qoe_probe_switches_to_configured_project_scope():
    script = (ROOT / "deploy/scripts/verify-horizon-qoe.sh").read_text()

    assert "OS_PROJECT_NAME" in script
    assert "OS_PROJECT_DOMAIN_NAME" in script
    assert '"$KEYSTONE_URL/auth/tokens"' in script
    assert 'data.get("token", {}).get("project", {}).get("id")' in script
    assert '"$HORIZON_URL/auth/switch/$project_id/"' in script
    assert script.index("auth/switch/$project_id") < script.index('pages=(')


def test_qoe_probe_attributes_samples_to_every_ready_replica():
    script = (ROOT / "deploy/scripts/verify-horizon-qoe.sh").read_text()
    values = (ROOT / "helm/openstack-helm/horizon/values.yaml").read_text()

    assert "X-DCN-QoE: 1" in script
    assert "X-DCN-Horizon-Backend" in script
    assert "expected_backends" in script
    assert "Horizon QoE did not exercise Ready replica" in script
    assert "median-budget-ratio" in script
    assert "HORIZON_REQUIRE_BACKEND_ATTRIBUTION" in script
    assert "legacy-unattributed" in script
    assert 'SetEnvIf X-DCN-QoE "^1$" dcn_qoe_probe' in values
    assert 'X-DCN-Horizon-Backend "expr=%{osenv:HOSTNAME}"' in values
