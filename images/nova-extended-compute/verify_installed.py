from pathlib import Path


root = Path("/var/lib/openstack/lib/python3.12/site-packages/nova")
api = (root / "compute/api.py").read_text()
assert "flyt_integration.prebuild" in api
assert "instance_uuids=flyt_instance_uuids" in api
assert "flyt.register_opts(CONF)" in (root / "conf/__init__.py").read_text()
assert 'availability_zone or "default"' in (root / "flyt.py").read_text()
assert (root / "cmd/conductor.py").is_file()
assert (root / "cmd/novncproxy.py").is_file()
assert (root / "wsgi/osapi_compute.py").is_file()
