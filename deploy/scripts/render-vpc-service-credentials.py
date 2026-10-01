#!/usr/bin/env python3
"""Render facade credentials to a pipe, never a plaintext intermediate file."""
import argparse
import base64
import json
from pathlib import Path
import ssl
import sys
from urllib.parse import urlsplit

import yaml


def render(source, ca_secret, identity_url):
    endpoint = urlsplit(identity_url)
    if (endpoint.scheme != "https" or not endpoint.hostname or endpoint.username
            or endpoint.password or endpoint.query or endpoint.fragment
            or not endpoint.path.rstrip("/").endswith("/v3")):
        raise ValueError("HTTPS identity v3 endpoint required")
    ca = base64.b64decode(ca_secret["data"]["ca.crt"], validate=True)
    if not ca or len(ca) > 65536:
        raise ValueError("invalid CA size")
    ssl.create_default_context(cadata=ca.decode())
    def get(key):
        value = base64.b64decode(source["data"][key], validate=True).decode()
        if not value:
            raise ValueError("missing credential field")
        return value
    auth = {key: get("OS_" + key.upper()) for key in (
        "username", "password", "project_name", "user_domain_name", "project_domain_name")}
    auth["auth_url"] = identity_url
    cloud = {"clouds": {"openstack": {"auth": auth, "region_name": get("OS_REGION_NAME"),
             "endpoint_type": get("OS_INTERFACE"), "identity_api_version": 3, "verify": True}}}
    return {"apiVersion": "v1", "kind": "Secret", "metadata": {
        "name": "vpc-facade-service-credentials", "namespace": "openstack"}, "type": "Opaque",
        "data": {"clouds.yaml": base64.b64encode(yaml.safe_dump(cloud, sort_keys=False).encode()).decode(),
                 "cacert": base64.b64encode(ca).decode()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ca-secret", required=True)
    parser.add_argument("--identity-url", required=True)
    parser.add_argument("--check", action="store_true", help="Validate without emitting credential data")
    args = parser.parse_args()
    result = render(json.load(sys.stdin), json.loads(Path(args.ca_secret).read_text()), args.identity_url)
    if not args.check:
        print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("Facade credential rendering failed; input withheld", file=sys.stderr)
        raise SystemExit(1) from None
