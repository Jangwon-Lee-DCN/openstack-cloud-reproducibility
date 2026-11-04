#!/usr/bin/env python3
"""Reject competing facade deployment inputs before the installer can write."""
import pathlib
import re
import sys

import yaml


def check(composite, scoped):
    if scoped.get("schema") != 1 or scoped.get("component") != "vpc-facade-credential-trust":
        raise ValueError("invalid scoped facade lock")
    candidate = scoped["candidate"]
    if not re.fullmatch(r"[0-9a-f]{40}", candidate["source_revision"]):
        raise ValueError("facade source must be pinned")
    image = candidate["image"]
    if not re.fullmatch(r"[^\s@]+@sha256:[0-9a-f]{64}", image):
        raise ValueError("facade image must be immutable")
    if composite["spec"]["facadeImage"] != image:
        raise ValueError("composite and scoped facade images disagree")
    if composite["spec"]["sourceRevision"] != candidate["source_revision"]:
        raise ValueError("composite source differs from qualified facade source")


def main():
    if len(sys.argv) != 3:
        raise ValueError("two lock paths required")
    check(*(yaml.safe_load(pathlib.Path(path).read_text()) for path in sys.argv[1:]))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, TypeError, AttributeError, OSError, yaml.YAMLError):
        # Never echo arbitrary lock input into operational logs.
        print("VPC facade locks are invalid or disagree; reconcile image and TLS inputs before deployment", file=sys.stderr)
        raise SystemExit(1) from None
