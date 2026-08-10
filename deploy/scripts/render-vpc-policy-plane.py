#!/usr/bin/env python3
"""Render the locked VPC images into a kustomize YAML stream."""
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
    seen = set()
    for document in documents:
        if not document or document.get("kind") != "Deployment":
            continue
        deployment = document["metadata"]["name"]
        for container in document["spec"]["template"]["spec"]["containers"]:
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
