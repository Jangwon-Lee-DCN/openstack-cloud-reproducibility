#!/usr/bin/env python3
"""Render the locked VPC images into a kustomize YAML stream."""
import copy
import os
import pathlib
import sys

import yaml


def ensure_facade_trust(pod, container):
    """Match the scoped trust transition without replacing foreign settings."""
    name = "openstack-public-ca"
    path = "/etc/vpc-facade/openstack-ca"

    def add_exact(items, desired):
        matches = [item for item in items if item.get("name") == desired["name"]]
        if matches:
            normalized = copy.deepcopy(matches)
            for item in normalized:
                if "secret" in desired and isinstance(item.get("secret"), dict):
                    item["secret"].setdefault("defaultMode", 0o644)
            if normalized != [desired]:
                raise ValueError("conflicting facade trust setting")
        else:
            items.append(desired)

    mounts = container.setdefault("volumeMounts", [])
    if any(item.get("mountPath") == path and item.get("name") != name for item in mounts):
        raise ValueError("facade CA mount path already occupied")
    add_exact(container.setdefault("env", []), {"name": "SSL_CERT_FILE", "value": path + "/ca.crt"})
    add_exact(mounts, {"name": name, "mountPath": path, "readOnly": True})
    add_exact(pod.setdefault("volumes", []), {"name": name, "secret": {
        "secretName": name, "defaultMode": 0o644, "items": [{"key": "ca.crt", "path": "ca.crt"}]}})


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: {sys.argv[0]} LOCK_FILE")
    lock = yaml.safe_load(pathlib.Path(sys.argv[1]).read_text())["spec"]
    controller_image = os.environ.get("VPC_CONTROLLER_IMAGE_OVERRIDE", lock["controllerImage"])
    allowed_controller_images = {
        lock["controllerImage"],
        lock["rollbackControllerImage"],
    }
    if controller_image not in allowed_controller_images:
        raise SystemExit("VPC_CONTROLLER_IMAGE_OVERRIDE is not an allowed locked image")
    if "@sha256:" not in controller_image:
        raise SystemExit("VPC controller image must be pinned by digest")
    replacements = {
        ("vpc-control-plane-controller-manager", "manager"): controller_image,
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
            if key == ("vpc-facade", "apiserver"):
                ensure_facade_trust(document["spec"]["template"]["spec"], container)
    missing = set(replacements) - seen
    if missing:
        raise SystemExit(f"rendered VPC resources lack locked containers: {sorted(missing)}")
    yaml.safe_dump_all(documents, sys.stdout, sort_keys=False)


if __name__ == "__main__":
    main()
