#!/usr/bin/env python3
"""Generate ephemeral Cinder/Manila Helm overrides from the CSI secret."""

import base64
import json
import os
import subprocess
import sys

import yaml


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: generate-powerstore-overrides.py cinder|manila OUTPUT")
    service, output = sys.argv[1:]
    if service not in {"cinder", "manila"}:
        raise SystemExit("service must be cinder or manila")
    raw = subprocess.check_output(
        ["kubectl", "get", "secret", "-n", "powerstore", "powerstore-config", "-o", "json"]
    )
    secret = json.loads(raw)
    config = yaml.safe_load(base64.b64decode(secret["data"]["config"]))
    array = next((item for item in config["arrays"] if item.get("isDefault")), config["arrays"][0])
    host = array["endpoint"].split("//", 1)[-1].split("/", 1)[0]
    if service == "cinder":
        values = {"conf": {"backends": {"rbd1": {
            "san_ip": host,
            "san_login": array["username"],
            "san_password": array["password"],
        }}}}
    else:
        values = {"conf": {"manila": {"powerstore": {
            "dell_nas_login": array["username"],
            "dell_nas_password": array["password"],
        }}}}
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        yaml.safe_dump(values, stream, sort_keys=True)


if __name__ == "__main__":
    main()
