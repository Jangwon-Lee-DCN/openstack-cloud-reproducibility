#!/usr/bin/env python3
"""Render the locked VPC images into a kustomize YAML stream."""
import os
import pathlib
import sys

import yaml


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: {sys.argv[0]} LOCK_FILE")
    lock = yaml.safe_load(pathlib.Path(sys.argv[1]).read_text())["spec"]
    replacements = {
        ("vpc-control-plane-controller-manager", "manager"): lock["controllerImage"],
        ("vpc-facade", "apiserver"): lock["facadeImage"],
    }
    documents = list(yaml.safe_load_all(sys.stdin))
    endpoint_cidrs = os.environ.get("VPC_ENDPOINT_SERVICE_CIDRS", "192.168.21.0/24")
    if not endpoint_cidrs or any(character.isspace() for character in endpoint_cidrs):
        raise SystemExit("VPC_ENDPOINT_SERVICE_CIDRS must be a non-empty comma-separated value without whitespace")
    seen = set()
    for document in documents:
        if not document or document.get("kind") != "Deployment":
            continue
        deployment = document["metadata"]["name"]
        for container in document["spec"]["template"]["spec"]["containers"]:
            args = container.get("args", [])
            container["args"] = [
                f"--vpc-endpoint-service-cidrs={endpoint_cidrs}"
                if argument.startswith("--vpc-endpoint-service-cidrs=")
                else argument
                for argument in args
            ]
            key = (deployment, container["name"])
            if key in replacements:
                container["image"] = replacements[key]
                seen.add(key)
    missing = set(replacements) - seen
    if missing:
        raise SystemExit(f"rendered VPC resources lack locked containers: {sorted(missing)}")
    yaml.safe_dump_all(documents, sys.stdout, sort_keys=False)


if __name__ == "__main__":
    main()
