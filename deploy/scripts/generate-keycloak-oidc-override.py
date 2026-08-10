#!/usr/bin/env python3
import os
import pathlib
import re
import subprocess
import sys
import base64
import yaml

if len(sys.argv) != 3:
    raise SystemExit("usage: generate-keycloak-oidc-override.py BASE_VALUES OUTPUT")
base_path, output_path = map(pathlib.Path, sys.argv[1:])
repo = pathlib.Path(__file__).resolve().parents[2]
services = pathlib.Path(os.environ.get("DCN_SERVICES_REPO", repo.parent / "openstack-cloud-services"))
secret_path = services / "deployment/prerequisites/identity/keycloak/secrets/keycloak-credentials.secret.sops.yaml"
secret_doc = yaml.safe_load(subprocess.check_output(["sops", "-d", str(secret_path)], text=True))
if "stringData" in secret_doc:
    client_secret = secret_doc["stringData"]["oidc-client-secret"]
else:
    client_secret = base64.b64decode(secret_doc["data"]["oidc-client-secret"]).decode()
base = yaml.safe_load(base_path.read_text())
wsgi = base["conf"]["wsgi_keystone"]
updated, count = re.subn(r'OIDCClientSecret\s+"[^"]*"', f'OIDCClientSecret "{client_secret}"', wsgi)
if count != 1:
    raise SystemExit("expected exactly one OIDCClientSecret directive")
pathlib.Path(output_path).write_text(yaml.safe_dump({"conf": {"wsgi_keystone": updated}}, sort_keys=False))
