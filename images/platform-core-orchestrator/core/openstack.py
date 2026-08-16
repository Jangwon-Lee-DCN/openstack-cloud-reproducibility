"""Minimal fail-closed OpenStack REST adapters.

The worker uses project-scoped application credentials supplied through a
Kubernetes Secret.  Endpoint URLs are explicit so a compromised catalog cannot
redirect provider traffic.  No administrator credential is accepted here.
"""
import json
import urllib.error
import urllib.parse
import urllib.request
import time

from .adapters import ComputeAdapter, NetworkAdapter, ProviderError, VolumeAdapter


class OpenStackSession:
    def __init__(self, auth_url, username, password, project_name, user_domain="Default",
                 project_domain="Default", endpoints=None, transport=None):
        required = [auth_url, username, password, project_name]
        if not all(required):
            raise RuntimeError("project-scoped OpenStack credentials are required")
        self.auth_url = auth_url.rstrip("/")
        self.username, self.password, self.project_name = username, password, project_name
        self.user_domain, self.project_domain = user_domain, project_domain
        self.endpoints = dict(endpoints or {})
        self.transport = transport or self._transport
        self.token = self.project_id = None

    @staticmethod
    def _transport(method, url, headers, body):
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                raw = response.read()
                return response.status, dict(response.headers), json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try: payload = json.loads(raw) if raw else {}
            except ValueError: payload = {}
            return exc.code, dict(exc.headers), payload
        except OSError as exc:
            raise ProviderError("OPENSTACK_UNAVAILABLE", retryable=True) from exc

    def authenticate(self):
        body = {"auth": {"identity": {"methods": ["password"], "password": {"user": {
            "name": self.username, "domain": {"name": self.user_domain}, "password": self.password}}},
            "scope": {"project": {"name": self.project_name, "domain": {"name": self.project_domain}}}}}
        status, headers, payload = self.transport("POST", self.auth_url + "/auth/tokens",
                                                   {"Content-Type": "application/json"},
                                                   json.dumps(body, separators=(",", ":")).encode())
        if status != 201:
            raise ProviderError("KEYSTONE_AUTH_FAILED", retryable=status >= 500)
        self.token = headers.get("X-Subject-Token") or headers.get("x-subject-token")
        self.project_id = payload.get("token", {}).get("project", {}).get("id")
        if not self.token or not self.project_id:
            raise ProviderError("KEYSTONE_SCOPE_INVALID", retryable=False)

    def request(self, service, method, path, payload=None, expected=(200, 201, 202, 204), headers=None):
        endpoint = self.endpoints.get(service)
        if not endpoint:
            raise ProviderError(f"{service.upper()}_ENDPOINT_MISSING", retryable=False)
        if not self.token: self.authenticate()
        encoded = None if payload is None else json.dumps(payload, separators=(",", ":")).encode()
        request_headers = {"Accept": "application/json", "X-Auth-Token": self.token}
        if encoded is not None: request_headers["Content-Type"] = "application/json"
        request_headers.update(headers or {})
        status, response_headers, response = self.transport(method, endpoint.rstrip("/") + path,
                                                              request_headers, encoded)
        if status == 401:
            self.authenticate(); request_headers["X-Auth-Token"] = self.token
            status, response_headers, response = self.transport(method, endpoint.rstrip("/") + path,
                                                                  request_headers, encoded)
        if status not in expected:
            raise ProviderError(f"{service.upper()}_HTTP_{status}", retryable=status == 429 or status >= 500 or (method == "DELETE" and status == 409))
        return response, response_headers

    def probe(self, service, path):
        return self.request(service, "GET", path, expected=(200, 203, 300))


class NovaAdapter(ComputeAdapter):
    def __init__(self, session): self.session = session

    def create_server(self, operation_id, spec):
        server_spec = spec.get("server", spec)
        name = server_spec.get("name", f"dcn-{operation_id[:12]}")
        existing, _ = self.session.request("nova", "GET", "/servers/detail?" + urllib.parse.urlencode({"name": name}))
        for server in existing.get("servers", []):
            if server.get("metadata", {}).get("dcn_operation_id") == operation_id:
                return server["id"]
        body = {"server": {"name": name,
                            "imageRef": server_spec["image_id"], "flavorRef": server_spec["flavor_id"],
                            "networks": [{"port": spec["port_id"]}],
                            "metadata": {"dcn_operation_id": operation_id}}}
        if spec.get("volume_id"):
            body["server"]["block_device_mapping_v2"] = [{"uuid": spec["volume_id"], "source_type": "volume",
                                                             "destination_type": "volume", "boot_index": 0,
                                                             "delete_on_termination": False}]
            body["server"].pop("imageRef", None)
        response, _ = self.session.request("nova", "POST", "/servers", body)
        return response["server"]["id"]

    def delete_server(self, server_id):
        self.session.request("nova", "DELETE", f"/servers/{server_id}", expected=(202, 204, 404))
        for _ in range(60):
            try: self.session.request("nova", "GET", f"/servers/{server_id}", expected=(200,))
            except ProviderError as exc:
                if exc.code == "NOVA_HTTP_404": return
                raise
            time.sleep(2)
        raise ProviderError("NOVA_DELETE_TIMEOUT", retryable=True)


class NeutronAdapter(NetworkAdapter):
    def __init__(self, session): self.session = session

    def create_port(self, operation_id, spec):
        name = spec.get("name", f"dcn-{operation_id[:12]}")
        existing, _ = self.session.request("neutron", "GET", "/v2.0/ports?" + urllib.parse.urlencode({"name": name}))
        for port in existing.get("ports", []):
            if port.get("description") == f"Track A operation {operation_id}": return port["id"]
        network_id = spec.get("network_id")
        if not network_id and spec.get("subnet_id"):
            subnet, _ = self.session.request("neutron", "GET", f"/v2.0/subnets/{spec['subnet_id']}")
            network_id = subnet["subnet"]["network_id"]
        if not network_id: raise ProviderError("NETWORK_REFERENCE_REQUIRED", retryable=False)
        port = {"network_id": network_id, "name": name,
                "admin_state_up": True, "description": f"Track A operation {operation_id}"}
        if spec.get("security_group_ids") is not None: port["security_groups"] = spec["security_group_ids"]
        if spec.get("subnet_id"): port["fixed_ips"] = [{"subnet_id": spec["subnet_id"]}]
        response, _ = self.session.request("neutron", "POST", "/v2.0/ports", {"port": port})
        return response["port"]["id"]

    def delete_port(self, port_id):
        self.session.request("neutron", "DELETE", f"/v2.0/ports/{port_id}", expected=(204, 404))


class CinderAdapter(VolumeAdapter):
    def __init__(self, session): self.session = session

    def create_volume(self, operation_id, spec):
        name = spec.get("name", f"dcn-{operation_id[:12]}")
        existing, _ = self.session.request("cinder", "GET", f"/v3/{self.session.project_id}/volumes/detail?" + urllib.parse.urlencode({"name": name}))
        for volume in existing.get("volumes", []):
            if volume.get("metadata", {}).get("dcn_operation_id") == operation_id: return volume["id"]
        volume = {"size": int(spec["size_gib"]), "name": name,
                  "metadata": {"dcn_operation_id": operation_id}}
        if spec.get("volume_type"): volume["volume_type"] = spec["volume_type"]
        if spec.get("image_id"): volume["imageRef"] = spec["image_id"]
        response, _ = self.session.request("cinder", "POST", f"/v3/{self.session.project_id}/volumes", {"volume": volume})
        return response["volume"]["id"]

    def delete_volume(self, volume_id):
        self.session.request("cinder", "DELETE", f"/v3/{self.session.project_id}/volumes/{volume_id}", expected=(202, 204, 404))
        for _ in range(60):
            try: self.session.request("cinder", "GET", f"/v3/{self.session.project_id}/volumes/{volume_id}", expected=(200,))
            except ProviderError as exc:
                if exc.code == "CINDER_HTTP_404": return
                raise
            time.sleep(2)
        raise ProviderError("CINDER_DELETE_TIMEOUT", retryable=True)
