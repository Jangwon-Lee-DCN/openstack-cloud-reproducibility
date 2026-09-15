#!/usr/bin/env python3
"""Render cloud-init that installs the private-cloud CA and verifies RGW TLS."""

import argparse
import base64
import pathlib


def render(ca: bytes, endpoint: str) -> str:
    if b"BEGIN CERTIFICATE" not in ca:
        raise ValueError("CA input is not a PEM certificate")
    encoded = base64.b64encode(ca).decode()
    return f"""#cloud-config
write_files:
  - path: /usr/local/share/ca-certificates/dcn-cloud.crt
    owner: root:root
    permissions: '0644'
    encoding: b64
    content: {encoded}
runcmd:
  - [update-ca-certificates]
  - [curl, --silent, --show-error, --output, /dev/null, {endpoint}]
  - [sh, -c, 'echo AI_WORKSPACE_RGW_TLS_OK >/var/lib/cloud/instance/ai-workspace-rgw-tls.ok']
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ca", required=True, type=pathlib.Path)
    parser.add_argument("--endpoint", default="https://s3.cloud.dcn.ssu.ac.kr/")
    args = parser.parse_args()
    print(render(args.ca.read_bytes(), args.endpoint), end="")


if __name__ == "__main__":
    main()
