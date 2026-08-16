#!/usr/bin/env python3
"""Static safety checks for RGW catalog ordering and Masakari read-only policy."""

from pathlib import Path

root = Path(__file__).resolve().parents[2]
script = (root / "deploy/scripts/reconcile-rgw-keystone-catalog.sh").read_text()
accept = script.index("urllib.request.urlopen")
catalog = script.index("openstack service create")
assert accept < catalog, "catalog must be created only after Swift token acceptance"
account_setting = script.index("ceph config set client.rgw.openstack.object.store.a rgw_swift_account_in_url true")
account_check = script.index("ceph config get client.rgw.openstack.object.store.a rgw_swift_account_in_url")
runtime_restart = script.index("rollout restart deployment/rook-ceph-rgw-$store-a")
runtime_check = script.index('ceph daemon "$socket" config get rgw_swift_account_in_url')
url_setting = script.index("ceph config set client.rgw.openstack.object.store.a rgw_keystone_url")
url_runtime_check = script.index('ceph daemon "$socket" config get rgw_keystone_url')
assert account_setting < account_check < runtime_restart < runtime_check < accept, (
    "AUTH_<project_id> handling must be persisted, loaded and runtime-verified before acceptance"
)
assert account_setting < url_setting < runtime_restart < url_runtime_check < accept
assert '"url":"http://keystone-api.openstack.svc.cluster.local:5000"' in script
assert "method='PUT'" in script and "?format=json" in script and "method='DELETE'" in script
assert script.index("method='PUT'") < script.index("?format=json") < script.index("method='DELETE'") < catalog
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
