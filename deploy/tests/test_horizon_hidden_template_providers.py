import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_hidden_network_panels_remain_template_providers():
    dockerfile = (ROOT / "images/horizon-complete/Dockerfile").read_text()

    assert (
        'ADD_INSTALLED_APPS = ["openstack_dashboard.dashboards.project.networks"]'
        in dockerfile
    )
    assert (
        'ADD_INSTALLED_APPS = ["openstack_dashboard.dashboards.project.routers"]'
        in dockerfile
    )
    removed_panels = re.search(
        r'rm -f "\$enabled/_1420_project_network_topology_panel\.py"(.+?)&& sed -i',
        dockerfile,
        re.DOTALL,
    ).group(1)
    assert "_1430_project_network_panel.py" not in removed_panels
    assert "_1440_project_routers_panel.py" not in removed_panels


def test_phase_60_loads_templates_used_by_hidden_admin_panels():
    verifier = (ROOT / "deploy/scripts/verify-horizon-capabilities.sh").read_text()

    assert '"project/networks/_network_ips.html"' in verifier
    assert '"project/routers/create.html"' in verifier
