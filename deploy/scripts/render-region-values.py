#!/usr/bin/env python3
"""Normalize legacy Keystone region names in decrypted Helm values."""

import os
import sys

import yaml


TARGET_REGION = os.environ.get("OPENSTACK_REGION", "seoul-ssu-1")
LEGACY_REGIONS = {"RegionOne", "RegionOne-VM"}


def normalize(value):
    if isinstance(value, dict):
        return {key: normalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize(item) for item in value]
    if isinstance(value, str) and value in LEGACY_REGIONS:
        return TARGET_REGION
    return value


document = normalize(yaml.safe_load(sys.stdin) or {})
identity_auth = (
    document.get("endpoints", {}).get("identity", {}).get("auth", {})
)
for credentials in identity_auth.values():
    if isinstance(credentials, dict):
        credentials["region_name"] = TARGET_REGION
yaml.safe_dump(document, sys.stdout, sort_keys=False)
