#!/usr/bin/env python3
import argparse
from pathlib import Path
import re


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--horizon-namespace", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--keystone-url", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[^\s]+@sha256:[0-9a-f]{64}", args.image):
        raise SystemExit("support API image must be pinned by sha256 digest")
    value = Path(args.template).read_text()
    replacements = {
        "@NAMESPACE@": args.namespace,
        "@HORIZON_NAMESPACE@": args.horizon_namespace,
        "@IMAGE@": args.image,
        "@KEYSTONE_URL@": args.keystone_url,
    }
    for key, replacement in replacements.items():
        value = value.replace(key, replacement)
    if re.search(r"@[A-Z_]+@", value):
        raise SystemExit("unresolved support center template placeholder")
    Path(args.output).write_text(value)


if __name__ == "__main__":
    main()
