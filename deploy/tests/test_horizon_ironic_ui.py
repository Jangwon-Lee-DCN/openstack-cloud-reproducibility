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
    assert "openstack.roles.admin" in dockerfile
    assert "openstack.services.baremetal" in dockerfile
    assert "window.jQuery.migrateMute = true;" in dockerfile


def test_ironic_ui_is_not_registered_as_a_project_panel():
    dockerfile = (ROOT / "images/horizon-complete/Dockerfile").read_text()

    assert "ironic_ui/enabled/_2200_ironic.py" in dockerfile
    assert "project_ironic" not in dockerfile
