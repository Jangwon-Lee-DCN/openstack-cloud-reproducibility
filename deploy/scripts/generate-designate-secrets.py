#!/usr/bin/env python3
"""Generate encrypted PowerDNS and Designate Helm values."""

import os
import secrets
import subprocess
import tempfile
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "secrets" / "heat.values.sops.yaml"
TARGETS = {
    "powerdns": ROOT / "secrets" / "powerdns.values.sops.yaml",
    "designate": ROOT / "secrets" / "designate.values.sops.yaml",
}

for target in TARGETS.values():
    if target.exists():
        raise SystemExit(f"refusing to overwrite {target}")

source = yaml.safe_load(subprocess.check_output(["sops", "-d", str(SOURCE)]))
identity_admin = source["endpoints"]["identity"]["auth"]["admin"]["password"]
db_admin = source["endpoints"]["oslo_db"]["auth"]["admin"]["password"]
rabbit_admin = source["endpoints"]["oslo_messaging"]["auth"]["admin"]["password"]


def password():
    return secrets.token_urlsafe(36)


powerdns_token = password()
documents = {
    "powerdns": {
        "endpoints": {
            "powerdns": {"auth": {"service": {"token": powerdns_token}}},
            "oslo_db": {
                "auth": {
                    "admin": {"password": db_admin},
                    "powerdns": {"password": password()},
                }
            },
        }
    },
    "designate": {
        "endpoints": {
            "identity": {
                "auth": {
                    "admin": {"password": identity_admin},
                    "designate": {"password": password()},
                }
            },
            "oslo_db": {
                "auth": {
                    "admin": {"password": db_admin},
                    "designate": {"password": password()},
                }
            },
            "oslo_messaging": {
                "auth": {
                    "admin": {"password": rabbit_admin},
                    "designate": {"password": password()},
                }
            },
            "powerdns": {"auth": {"service": {"token": powerdns_token}}},
        }
    },
}

old_umask = os.umask(0o077)
try:
    for name, target in TARGETS.items():
        with tempfile.NamedTemporaryFile(
            "w", suffix=".values.sops.yaml", delete=False
        ) as stream:
            yaml.safe_dump(documents[name], stream, sort_keys=False)
            plaintext = Path(stream.name)
        try:
            subprocess.run(
                ["sops", "--encrypt", "--output", str(target), str(plaintext)],
                cwd=ROOT.parent.parent,
                check=True,
            )
        finally:
            plaintext.unlink(missing_ok=True)
finally:
    os.umask(old_umask)

for target in TARGETS.values():
    print(f"created encrypted values: {target}")
