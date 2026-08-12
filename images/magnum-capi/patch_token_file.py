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
    "import secrets\nimport yaml\n",
    "import copy\nimport secrets\nimport yaml\n",
)
source = source.replace(
    '                        service_type="identity", interface="public"\n',
    '                        service_type="identity",\n'
    "                        interface=CONF.capi_helm.app_cred_interface_type,\n"
    "                        region_name=osc.cinder_region_name(),\n"
)
source = source.replace(
    '    return {\n'
    '        "clouds": {\n'
    '            "openstack": {\n',
    '    clouds_dict = {\n'
    '        "clouds": {\n'
    '            "openstack": {\n',
    1,
)
source = source.replace(
    "        },\n"
    "    }\n"
    "\n"
    "\n"
    "def get_app_cred_string_data(context, app_cred):\n",
    "        },\n"
    "    }\n"
    '    clouds_dict["clouds"]["openstack-capo"] = copy.deepcopy(\n'
    '        clouds_dict["clouds"]["openstack"]\n'
    "    )\n"
    '    clouds_dict["clouds"]["openstack-capo"]["region_name"] = (\n'
    "        CONF.nova_client.region_name\n"
    "    )\n"
    "    return clouds_dict\n"
    "\n"
    "\n"
    "def get_app_cred_string_data(context, app_cred):\n",
    1,
)
if "region_name=osc.cinder_region_name()" not in source:
    raise SystemExit("internal identity endpoint patch did not apply")
if '"openstack-capo"' not in source:
    raise SystemExit("CAPO-specific cloud patch did not apply")
app_creds.write_text(source)

driver = path.with_name("driver.py")
source = driver.read_text()
source = source.replace(
    '            "kubernetesVersion": kube_version,\n',
    '            "kubernetesVersion": kube_version,\n'
    "            # CAPO uses a second cloud entry without a region in the\n"
    "            # identityRef, preserving standard providerID formatting.\n"
    '            "infrastructureCloudName": "openstack-capo",\n',
)
source = source.replace(
    '                "enableLoadBalancer": True,\n',
    "                # The upstream driver intentionally forces an API load\n"
    "                # balancer. Honour the Magnum ClusterTemplate field for\n"
    "                # the explicit PoC comparison; a no-LB cluster retains\n"
    "                # an API floating IP on its single control-plane node.\n"
    '                "enableLoadBalancer": bool(\n'
    "                    cluster.cluster_template.master_lb_enabled\n"
    "                ),\n",
)
source = source.replace(
    '        true_conditions = {\n'
    '            cond["type"]\n'
    '            for cond in capi_cluster.get("status", {}).get("conditions", [])\n'
    '            if cond["status"] == "True"\n'
    '        }\n',
    '        status = capi_cluster.get("status", {})\n'
    '        conditions = list(status.get("conditions", []))\n'
    '        # Cluster API v1.11 exposes the legacy Ready and\n'
    '        # ControlPlaneReady conditions under status.deprecated.v1beta1.\n'
    '        # Retain compatibility until magnum-capi-helm consumes the new\n'
    '        # Available/ControlPlaneAvailable condition contract.\n'
    '        conditions.extend(\n'
    '            status.get("deprecated", {}).get("v1beta1", {}).get(\n'
    '                "conditions", []\n'
    '            )\n'
    '        )\n'
    '        true_conditions = {\n'
    '            cond["type"] for cond in conditions\n'
    '            if cond["status"] == "True"\n'
    '        }\n',
)
if "cluster.cluster_template.master_lb_enabled" not in source:
    raise SystemExit("master_lb_enabled patch did not apply")
if '"infrastructureCloudName": "openstack-capo"' not in source:
    raise SystemExit("infrastructure cloud-name patch did not apply")
if 'status.get("deprecated", {}).get("v1beta1", {})' not in source:
    raise SystemExit("Cluster API v1beta1 compatibility patch did not apply")
driver.write_text(source)

wsgi = Path("/var/lib/openstack/bin/magnum-api-wsgi")
wsgi.write_text(
    "#!/usr/bin/env python3\n"
    "from magnum.api import app\n"
    "application = app.build_wsgi_app()\n"
)
wsgi.chmod(0o755)
