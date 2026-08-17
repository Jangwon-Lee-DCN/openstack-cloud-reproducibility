#!/usr/bin/env python3
"""Validate and reconcile the supported DCN Glance image catalogue."""

import argparse
import datetime
import json
import subprocess
import sys

import yaml


def command(*args):
    return subprocess.run(["openstack", *args], check=True, text=True,
                          capture_output=True).stdout


def load_catalog(path):
    with open(path, encoding="utf-8") as stream:
        catalog = yaml.safe_load(stream)
    if catalog.get("schema") != "dcn.glance.catalog/v1":
        raise ValueError("unsupported catalogue schema")
    names = [item["name"] for item in catalog.get("images", [])]
    if not names or len(names) != len(set(names)):
        raise ValueError("catalogue image names must be present and unique")
    for item in catalog["images"]:
        if item.get("os_distro") != "ubuntu":
            raise ValueError(f"non-Ubuntu platform image is forbidden: {item['name']}")
        if item["workload_type"] == "general" and item.get("hidden"):
            raise ValueError(f"general image must be visible: {item['name']}")
        if item["workload_type"] == "capi" and item.get("hidden"):
            raise ValueError(f"CAPI image must be visible: {item['name']}")
        if item["workload_type"] == "amphora" and not item.get("hidden"):
            raise ValueError(f"Amphora image must be hidden: {item['name']}")
    return catalog


def all_images():
    visible = json.loads(command("image", "list", "--long", "-f", "json"))
    hidden = json.loads(command("image", "list", "--long", "--hidden", "-f", "json"))
    return visible + hidden


def field(image, name):
    return image.get(name, image.get(name.lower().replace(" ", "_")))


def as_bool(value):
    return value is True or str(value).lower() == "true"


def reconcile(catalog, apply=False):
    inventory = all_images()
    by_name = {}
    for image in inventory:
        by_name.setdefault(field(image, "Name"), []).append(image)
    errors = []
    changed = 0
    today = datetime.date.today().isoformat()
    for desired in catalog["images"]:
        matches = by_name.get(desired["name"], [])
        if len(matches) != 1:
            errors.append(f"{desired['name']}: expected one image, found {len(matches)}")
            continue
        image = matches[0]
        identifier = field(image, "ID")
        details = json.loads(command("image", "show", identifier, "-f", "json"))
        properties = details.get("properties", {}) or {}
        updates = []
        expected_properties = {
            "dcn_image_class": desired["class"],
            "dcn_workload_type": desired["workload_type"],
            "dcn_support_status": desired["support_status"],
            "dcn_catalog_schema": catalog["schema"],
            "os_distro": desired["os_distro"],
            "os_version": desired["os_version"],
        }
        if desired.get("kube_version"):
            expected_properties["kube_version"] = desired["kube_version"]
        for key, value in expected_properties.items():
            if str(properties.get(key, "")) != str(value):
                updates.extend(("--property", f"{key}={value}"))
                if not apply:
                    errors.append(f"{desired['name']}: {key}={properties.get(key)!r}, expected {value!r}")
        if apply and updates:
            command("image", "set", *updates, identifier)
            changed += 1
        visibility = str(details.get("visibility", "")).lower()
        if visibility != desired["visibility"]:
            if apply:
                command("image", "set", f"--{desired['visibility']}", identifier)
                changed += 1
            else:
                errors.append(f"{desired['name']}: visibility={visibility}")
        hidden = as_bool(properties.get("os_hidden", details.get("os_hidden")))
        if hidden != desired["hidden"]:
            if apply:
                command("image", "set", "--hidden" if desired["hidden"] else "--unhidden", identifier)
                changed += 1
            else:
                errors.append(f"{desired['name']}: hidden={hidden}")
        protected = as_bool(details.get("protected"))
        if protected != desired["protected"]:
            if apply:
                command("image", "set", "--protected" if desired["protected"] else "--unprotected", identifier)
                changed += 1
            else:
                errors.append(f"{desired['name']}: protected={protected}")
        actual_tags = set(details.get("tags", []))
        for tag in desired.get("tags", []):
            if tag not in actual_tags:
                if apply:
                    command("image", "set", "--tag", tag, identifier)
                    changed += 1
                else:
                    errors.append(f"{desired['name']}: missing tag {tag}")
        if apply:
            command("image", "set", "--property", f"dcn_last_reconciled={today}", identifier)
    checksums = {}
    for image in inventory:
        checksum = field(image, "Checksum")
        if checksum:
            checksums.setdefault(checksum, []).append(field(image, "Name"))
    for checksum, names in checksums.items():
        if len(names) > 1:
            errors.append(f"duplicate checksum {checksum}: {', '.join(sorted(names))}")
    print(json.dumps({"targets": len(catalog["images"]), "changed": changed,
                      "errors": errors}, sort_keys=True))
    return 1 if errors else 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("apply", "verify"))
    parser.add_argument("catalog")
    args = parser.parse_args()
    try:
        return reconcile(load_catalog(args.catalog), apply=args.mode == "apply")
    except (ValueError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        detail = getattr(exc, "stderr", None) or getattr(exc, "stdout", None) or str(exc)
        print(f"catalogue reconciliation failed: {str(detail).strip()}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
