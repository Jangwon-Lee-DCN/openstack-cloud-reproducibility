#!/usr/bin/env python3
"""Static safety checks for RGW catalog ordering and Masakari read-only policy."""

from pathlib import Path

root = Path(__file__).resolve().parents[2]
script = (root / "deploy/scripts/reconcile-rgw-keystone-catalog.sh").read_text()
accept = script.index("urllib.request.urlopen")
catalog = script.index("openstack service create")
assert accept < catalog, "catalog must be created only after Swift token acceptance"
for interface in ("public", "internal", "admin"):
    assert f"endpoint create --region $region \"\\$service_id\" {interface}" in script

values = (root / "deploy/values/site/masakari.yaml").read_text()
for resource in ("segments", "os-hosts", "notifications", "vmoves", "extensions"):
    assert f"os_masakari_api:{resource}:index" in values
    assert f"os_masakari_api:{resource}:detail" in values
for mutation in ("create", "update", "delete"):
    assert f":{mutation}:" not in values, "write policies must retain upstream admin default"

route = (root / "deploy/manifests/rgw-swift-route.yaml").read_text()
assert "s3.cloud.dcn.ssu.ac.kr" in route and "PathPrefix, value: /swift" in route
