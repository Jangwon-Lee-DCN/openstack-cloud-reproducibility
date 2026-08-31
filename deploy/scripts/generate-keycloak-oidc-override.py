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
metadata_url = (
    "http://keycloak-service.keycloak.svc.cluster.local:8080/realms/dcn/"
    ".well-known/openid-configuration"
)
updated, count = re.subn(
    r'OIDCProviderMetadataURL\s+"[^"]*"',
    f'OIDCProviderMetadataURL "{metadata_url}"',
    updated,
)
if count != 1:
    raise SystemExit("expected exactly one OIDCProviderMetadataURL directive")
updated, count = re.subn(
    r'OIDCSessionType\s+"[^"]*"',
    'OIDCSessionType "client-cookie:persistent:store_id_token"\n'
    '    OIDCLogoutRequestParams "client_id=keystone"',
    updated,
)
if count != 1:
    raise SystemExit("expected exactly one OIDCSessionType directive")
ca_directive = 'OIDCCABundlePath "/usr/local/share/ca-certificates/openstack-public-ca.crt"'
if "OIDCCABundlePath" not in updated:
    updated, count = re.subn(
        r"(OIDCSSLValidateServer\s+On)",
        rf"\1\n    {ca_directive}",
        updated,
    )
    if count != 1:
        raise SystemExit("expected exactly one OIDCSSLValidateServer On directive")
websso_aliases = """
    # Horizon names the configured authentication choice, whereas Keystone's
    # stock example protects only the protocol-named /websso/openid path.
    # Protect the actual keycloak_dcn URL emitted by Horizon as well.
    <Location /v3/auth/OS-FEDERATION/websso/keycloak_dcn>
        AuthType openid-connect
        Require valid-user
    </Location>
    <Location /identity/v3/auth/OS-FEDERATION/websso/keycloak_dcn>
        AuthType openid-connect
        Require valid-user
    </Location>
    <Location /identity/v3/auth/OS-FEDERATION/websso/openid>
        AuthType openid-connect
        Require valid-user
    </Location>
"""
if "/websso/keycloak_dcn>" not in updated:
    marker = "</VirtualHost>"
    if marker not in updated:
        raise SystemExit("expected a VirtualHost terminator in wsgi-keystone.conf")
    updated = updated.replace(marker, websso_aliases + "\n" + marker, 1)
pathlib.Path(output_path).write_text(yaml.safe_dump({"conf": {"wsgi_keystone": updated}}, sort_keys=False))
