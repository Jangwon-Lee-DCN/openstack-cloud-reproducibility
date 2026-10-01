import base64
from pathlib import Path
import subprocess
import tarfile

import yaml


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
    assert "X-Horizon-Backend" in script
    assert "expected_backends" in script
    assert "Horizon QoE did not exercise Ready replica" in script
    assert "median-budget-ratio" in script
    assert "HORIZON_REQUIRE_BACKEND_ATTRIBUTION" in script
    assert "legacy-unattributed" in script
    assert "HORIZON_ENFORCE_ABSOLUTE_BUDGETS" in script
    assert "exceeds advisory" in script
    assert "exceeds enforced" in script
    assert 'SetEnvIf X-DCN-QoE "^1$" dcn_qoe_probe' in values
    assert 'X-Horizon-Backend "expr=%{osenv:HOSTNAME}"' in values


def test_locked_horizon_package_contains_backend_attribution_config():
    package = ROOT / "helm/packages/patched/horizon-2026.1.0.tgz"
    with tarfile.open(package, "r:gz") as archive:
        packaged_values = archive.extractfile("horizon/values.yaml")
        assert packaged_values is not None
        values = packaged_values.read().decode()

    assert 'SetEnvIf X-DCN-QoE "^1$" dcn_qoe_probe' in values
    assert 'X-Horizon-Backend "expr=%{osenv:HOSTNAME}"' in values


def test_locked_horizon_package_renders_backend_attribution_config():
    rendered = subprocess.run(
        [
            "helm",
            "template",
            "horizon",
            str(ROOT / "helm/packages/patched/horizon-2026.1.0.tgz"),
            "-f",
            str(ROOT / "deploy/values/site/horizon.yaml"),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    objects = [item for item in yaml.safe_load_all(rendered) if item]
    secret = next(
        item
        for item in objects
        if item.get("kind") == "Secret"
        and item.get("metadata", {}).get("name") == "horizon-etc"
    )
    apache = base64.b64decode(secret["data"]["horizon.conf"]).decode()

    assert 'SetEnvIf X-DCN-QoE "^1$" dcn_qoe_probe' in apache
    assert 'X-Horizon-Backend "expr=%{osenv:HOSTNAME}"' in apache
