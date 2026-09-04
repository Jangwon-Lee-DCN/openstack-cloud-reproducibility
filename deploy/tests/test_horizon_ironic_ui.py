from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_ironic_ui_is_versioned_verified_and_admin_only():
    dockerfile = (ROOT / "images/horizon-complete/Dockerfile").read_text()

    assert "ironic_ui-6.8.0-py3-none-any.whl" in dockerfile
    assert "python_ironicclient-6.0.0-py3-none-any.whl" in dockerfile
    assert "0f3f09ce5f9c080005ad110f0b76181c7a361f19c36049e0841e4fd33a7e3a65" in dockerfile
    assert "4ae61cab95453db196123574601a8f84b520c6459d39a1bfbbaf502841d2a6d0" in dockerfile
    assert "ironic_ui/enabled/_2200_ironic.py" in dockerfile
    assert 'test -f "$local_enabled/_2200_ironic.py"' in dockerfile
    assert "PANEL_DASHBOARD = 'admin'" in dockerfile
    assert "openstack.services.baremetal" in dockerfile
    assert "DCN_BAREMETAL_ADMIN_PROJECT_ID" in dockerfile
    assert "baremetal_admin" in dockerfile
    assert "window.jQuery.migrateMute = true;" in dockerfile


def test_ironic_ui_is_not_registered_as_a_project_panel():
    dockerfile = (ROOT / "images/horizon-complete/Dockerfile").read_text()

    assert "ironic_ui/enabled/_2200_ironic.py" in dockerfile
    assert "project_ironic" not in dockerfile


def test_full_ironic_panel_policy_is_project_id_and_role_scoped():
    policy = (ROOT / "images/horizon-complete/ironic_policy/panel.py").read_text()
    setting = (ROOT / "images/horizon-complete/settings/0002_baremetal_access.py").read_text()

    assert 'getattr(user, "project_id", None) != expected_project' in policy
    assert '"baremetal_admin" in roles' in policy
    assert 'permissions = ("openstack.services.baremetal",)' in policy
    assert "openstack.roles.admin" not in policy
    assert 'getattr(settings, "DCN_BAREMETAL_ADMIN_PROJECT_ID", "")' in policy
    assert 'os.environ.get("DCN_BAREMETAL_ADMIN_PROJECT_ID", "")' in setting
    assert 'os.environ.get("DCN_BAREMETAL_DOMAIN_ID", "")' in setting
    assert "project_name" not in policy


def test_every_horizon_builder_copies_the_policy_and_setting():
    for relative in ("deploy/scripts/build-images.sh", "deploy/scripts/build-horizon-image.sh"):
        builder = (ROOT / relative).read_text()
        assert "ironic_policy/panel.py" in builder
        assert "settings/0002_baremetal_access.py" in builder


def test_project_access_and_dcn_approval_panels_are_built_from_separate_plugin():
    dockerfile = (ROOT / "images/horizon-complete/Dockerfile").read_text()
    assert "openstack_baremetal_access_dashboard.whl" in dockerfile
    assert "_1390_project_baremetal_access.py" in dockerfile
    assert "_2210_admin_baremetal_approvals.py" in dockerfile
    assert "baremetal_access_dashboard" in dockerfile


def test_every_horizon_builder_uses_baremetal_dashboard_repository():
    for relative in ("deploy/scripts/build-images.sh", "deploy/scripts/build-horizon-image.sh"):
        builder = (ROOT / relative).read_text()
        assert "BAREMETAL_ACCESS_DASHBOARD_REPO" in builder
        assert "openstack_baremetal_access_dashboard-*.whl" in builder


def test_horizon_reconciler_allows_only_the_approved_rollback_override():
    reconciler = (ROOT / "deploy/scripts/reconcile-full-stack.sh").read_text()
    assert "HORIZON_IMAGE_OVERRIDE" in reconciler
    assert "HORIZON_ROLLBACK_IMAGE=registry.dcn.ssu.ac.kr/openstack/horizon:source-ab566138b30c69bd2da4@sha256:1fe19f68553a2a955ba65e0ca46f3edb652fac16a1e4821591bc86ca5bd6becd" in reconciler
    assert "override is restricted to the production-approved rollback digest" in reconciler
