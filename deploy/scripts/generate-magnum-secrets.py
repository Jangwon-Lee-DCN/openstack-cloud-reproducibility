#!/usr/bin/env python3
"""Generate encrypted Magnum values without persisting plaintext."""

import os
import secrets
import subprocess
import tempfile
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "secrets" / "heat.values.sops.yaml"
TARGET = ROOT / "secrets" / "magnum.values.sops.yaml"

if TARGET.exists():
    raise SystemExit(f"refusing to overwrite {TARGET}")

source = yaml.safe_load(subprocess.check_output(["sops", "-d", str(SOURCE)]))
identity_admin = source["endpoints"]["identity"]["auth"]["admin"]["password"]
db_admin = source["endpoints"]["oslo_db"]["auth"]["admin"]["password"]
rabbit_admin = source["endpoints"]["oslo_messaging"]["auth"]["admin"]["password"]


def password():
    return secrets.token_urlsafe(36)


values = {
    "endpoints": {
        "identity": {
            "auth": {
                "admin": {"password": identity_admin},
                "magnum": {"password": password()},
                "magnum_stack_user": {"password": password()},
            }
        },
        "oslo_db": {
            "auth": {
                "admin": {"password": db_admin},
                "magnum": {"password": password()},
            }
        },
        "oslo_messaging": {
            "auth": {
                "admin": {"password": rabbit_admin},
                "magnum": {"password": password()},
            }
        },
    }
}

old_umask = os.umask(0o077)
try:
    with tempfile.NamedTemporaryFile(
        "w", suffix=".values.sops.yaml", delete=False
    ) as stream:
        yaml.safe_dump(values, stream, sort_keys=False)
        plaintext = Path(stream.name)
    try:
        subprocess.run(
            ["sops", "--encrypt", "--output", str(TARGET), str(plaintext)],
            cwd=ROOT.parent.parent,
            check=True,
        )
    finally:
        plaintext.unlink(missing_ok=True)
finally:
    os.umask(old_umask)

print(f"created encrypted values: {TARGET}")
