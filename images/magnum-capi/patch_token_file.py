#!/usr/bin/env python3
"""Add rotating projected-ServiceAccount tokenFile support to the driver."""

from pathlib import Path


path = Path(
    "/var/lib/openstack/lib/python3.12/site-packages/"
    "magnum_capi_helm/kubernetes.py"
)
source = path.read_text()
source = source.replace(
    '        elif user.get("token"):\n'
    '            self.headers.update({"Authorization": f"Bearer {user[\'token\']}"})\n'
    "        else:\n",
    '        elif user.get("token"):\n'
    '            self.headers.update({"Authorization": f"Bearer {user[\'token\']}"})\n'
    '            self._token_file = None\n'
    '        elif user.get("tokenFile"):\n'
    '            self._token_file = user["tokenFile"]\n'
    "        else:\n",
)
source = source.replace(
    "    def request(self, method, url, *args, **kwargs):\n"
    "        # Make sure to add the server to any relative URLs\n",
    "    def request(self, method, url, *args, **kwargs):\n"
    '        if getattr(self, "_token_file", None):\n'
    '            token = pathlib.Path(self._token_file).read_text().strip()\n'
    '            self.headers.update({"Authorization": f"Bearer {token}"})\n'
    "        # Make sure to add the server to any relative URLs\n",
)
if 'user.get("tokenFile")' not in source:
    raise SystemExit("tokenFile authentication patch did not apply")
path.write_text(source)

app_creds = path.with_name("common") / "app_creds.py"
source = app_creds.read_text()
source = source.replace(
    '                        service_type="identity", interface="public"\n',
    '                        service_type="identity",\n'
    "                        interface=CONF.capi_helm.app_cred_interface_type,\n"
    "                        region_name=osc.cinder_region_name(),\n"
)
if "region_name=osc.cinder_region_name()" not in source:
    raise SystemExit("internal identity endpoint patch did not apply")
app_creds.write_text(source)

wsgi = Path("/var/lib/openstack/bin/magnum-api-wsgi")
wsgi.write_text(
    "#!/usr/bin/env python3\n"
    "from magnum.api import app\n"
    "application = app.build_wsgi_app()\n"
)
wsgi.chmod(0o755)
