#!/usr/bin/env python3
"""Reconcile deletion protection for platform and Amphora Glance images."""

import argparse
import json
import os
import subprocess
import sys


def run_command(*args):
    completed = subprocess.run(
        ["openstack", *args], check=True, text=True, capture_output=True)
    return completed.stdout


def image_list(*filters):
    return json.loads(run_command(
        "image", "list", "--long", "--status", "active", *filters,
        "-f", "json"))


def normalized_tags(image):
    tags = image.get("Tags", image.get("tags", []))
    if isinstance(tags, str):
        return {item.strip() for item in tags.strip("[]").split(",") if item.strip()}
    return set(tags or [])


def image_id(image):
    return image.get("ID", image.get("id"))


def visibility(image):
    return str(image.get("Visibility", image.get("visibility", ""))).lower()


def protection_targets():
    targets = {}
    for image in image_list("--public"):
        if visibility(image) == "public":
            targets[image_id(image)] = "public"
    for image in image_list("--hidden"):
        if "amphora" in normalized_tags(image):
            targets[image_id(image)] = "hidden-amphora"
    if not targets:
        raise RuntimeError("no active public or hidden Amphora images found")
    return targets


def as_bool(value):
    return value is True or str(value).lower() == "true"


def reconcile(mode):
    targets = protection_targets()
    changed = False
    for identifier, target_type in sorted(targets.items()):
        details = json.loads(run_command("image", "show", identifier, "-f", "json"))
        protected = as_bool(details.get("protected"))
        properties = details.get("properties", {}) or {}
        if target_type == "hidden-amphora":
            if visibility(details) != "private":
                raise RuntimeError(f"Amphora image {identifier} is not private")
            if not as_bool(properties.get("os_hidden", details.get("os_hidden"))):
                raise RuntimeError(f"Amphora image {identifier} is not hidden")
        if mode == "apply" and not protected:
            run_command("image", "set", "--protected", identifier)
            protected = True
            changed = True
        elif mode == "rollback" and protected:
            run_command("image", "set", "--unprotected", identifier)
            protected = False
            changed = True
        if mode in ("apply", "verify") and not protected:
            raise RuntimeError(f"image {identifier} is not protected")
        print(f"{mode}: {identifier} ({target_type}) protected={str(protected).lower()}")
    print(f"summary: targets={len(targets)} changed={str(changed).lower()}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("apply", "verify", "rollback"))
    args = parser.parse_args()
    if args.mode == "rollback" and os.getenv("APPROVE_GLANCE_IMAGE_UNPROTECT") != "yes":
        parser.error("rollback requires APPROVE_GLANCE_IMAGE_UNPROTECT=yes")
    try:
        reconcile(args.mode)
    except (RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"glance image protection failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
