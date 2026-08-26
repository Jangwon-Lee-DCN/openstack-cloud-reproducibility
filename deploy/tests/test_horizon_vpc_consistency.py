from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_composite_image_requires_hidden_panel_action_and_facade_only_vpc_inventory():
    dockerfile = (ROOT / "images/horizon-complete/Dockerfile").read_text()
    assert 'remove_stock_actions(tables.InstancesTable, {"associate", "disassociate"})' in dockerfile
    assert "test ! -e /var/lib/openstack/lib/python3.12/site-packages/openstack_vpc_dashboard/api/native_inventory.py" in dockerfile
