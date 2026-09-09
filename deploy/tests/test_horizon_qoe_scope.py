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
