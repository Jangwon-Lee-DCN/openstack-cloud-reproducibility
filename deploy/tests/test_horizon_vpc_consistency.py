from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_composite_image_requires_hidden_panel_action_and_native_inventory_fix():
    dockerfile = (ROOT / "images/horizon-complete/Dockerfile").read_text()
    assert 'remove_stock_actions(tables.InstancesTable, {"associate", "disassociate"})' in dockerfile
    assert "Native Neutron (not VPC-managed)" in dockerfile
