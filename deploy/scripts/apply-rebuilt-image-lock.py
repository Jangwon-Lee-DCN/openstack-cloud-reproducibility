#!/usr/bin/env python3
"""Promote source-rebuilt OCI digests into every in-repository deployment pin."""
from pathlib import Path
import argparse
import re

root = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser()
parser.add_argument("--input", default=root / "deploy/generated/rebuilt-images.env", type=Path)
parser.add_argument("--apply", action="store_true", help="write replacements; default is a report")
parser.add_argument("--scope", choices=("full", "vpc", "magnum"), default="full", help="require/promote the full rebuild, four VPC binaries, or Magnum GitOps trio")
args = parser.parse_args()

refs = {}
for line in args.input.read_text().splitlines():
    if line and not line.startswith("#"):
        key, value = line.split("=", 1)
        if "@sha256:" not in value:
            raise SystemExit(f"non-immutable rebuilt reference for {key}: {value}")
        refs[key] = value

repo_for_key = {
    "gnocchi": "gnocchi", "ceilometer": "ceilometer", "aodh": "aodh",
    "keystone_oidc": "keystone", "keycloak": "keycloak",
    "neutron_fwaas": "neutron", "octavia_ovn": "octavia",
    "magnum_capi": "magnum", "magnum_capi_gitops": "magnum-capi-gitops",
    "magnum_capi_repository_writer": "magnum-capi-repository-writer",
    "vpc_control_plane": "vpc-control-plane", "vpc_facade": "vpc-facade",
    "vpc_metadata_attestor": "vpc-metadata-attestor", "vpc_endpoint_agent": "vpc-endpoint-agent",
    "horizon_complete": "horizon", "project_facade": "project-facade",
    "capo_controller": "capo-controller",
}
vpc_keys = {"vpc_control_plane", "vpc_facade", "vpc_metadata_attestor", "vpc_endpoint_agent"}
magnum_keys = {"magnum_capi", "magnum_capi_gitops", "magnum_capi_repository_writer"}
required_keys = set(repo_for_key) if args.scope == "full" else vpc_keys if args.scope == "vpc" else magnum_keys
missing = sorted(required_keys - set(refs))
if missing:
    raise SystemExit("rebuilt image result is incomplete: " + ", ".join(missing))

files = list((root / "deploy/values/site").glob("*.yaml"))
files += list((root / "deploy/manifests").glob("*.yaml"))
files += list((root / "prerequisites/cluster-api").rglob("*.yaml"))
# These repositories are explicit, commit-pinned rebuild inputs and own the
# Keycloak, VPC, and Magnum GitOps runtime manifests. Update them in the same
# review transaction when they are present beside this repository.
for sibling, patterns in {
    "openstack-cloud-services": ("deployment/**/*.yaml", "deployment/**/*.yml"),
    "vpc-control-plane": ("config/**/*.yaml",),
    "magnum-capi-gitops": ("**/*.yaml",),
}.items():
    sibling_root = root.parent / sibling
    for pattern in patterns:
        files += list(sibling_root.glob(pattern)) if sibling_root.exists() else []
changes = []
for path in files:
    original = path.read_text()
    updated = original
    for key, repository in repo_for_key.items():
        if key not in refs:
            continue
        replacement = refs[key]
        pattern = rf"registry\.dcn\.ssu\.ac\.kr/openstack/{re.escape(repository)}(?::[^\s\"']+)?@sha256:[a-f0-9]{{64}}"
        updated = re.sub(pattern, replacement, updated)
    if updated != original:
        try:
            display = path.relative_to(root)
        except ValueError:
            display = Path("..") / path.relative_to(root.parent)
        changes.append(display)
        if args.apply:
            path.write_text(updated)

# Kustomize stores VPC repository and digest in separate scalar fields rather
# than one OCI reference, so update that lock structurally after the generic
# full-reference replacements.
vpc_kustomization = root.parent / "vpc-control-plane/config/production/kustomization.yaml"
if vpc_kustomization.exists() and args.scope in ("full", "vpc"):
    original = vpc_kustomization.read_text()
    updated = original
    for key, name in (("vpc_control_plane", "vpc-control-plane"), ("vpc_facade", "vpc-facade")):
        repository, digest = refs[key].rsplit("@", 1)
        block = re.compile(
            rf"(\s+- name:\s+{re.escape('controller' if key == 'vpc_control_plane' else 'vpc-apiserver')}\n)"
            rf"(\s+newName:)\s+[^\n]+\n"
            rf"(\s+digest:)\s+sha256:[a-f0-9]{{64}}"
        )
        updated, count = block.subn(rf"\1\2 {repository}\n\3 {digest}", updated)
        if count != 1:
            raise SystemExit(f"could not uniquely update VPC kustomize image block for {name}")
    if updated != original and Path("../vpc-control-plane/config/production/kustomization.yaml") not in changes:
        changes.append(Path("../vpc-control-plane/config/production/kustomization.yaml"))
        if args.apply:
            vpc_kustomization.write_text(updated)

vpc_lock = root / "deploy/locks/vpc-policy-images.yaml"
vpc_source = root.parent / "vpc-control-plane"
if vpc_lock.exists() and vpc_source.exists() and args.scope in ("full", "vpc"):
    import subprocess
    import yaml
    document = yaml.safe_load(vpc_lock.read_text())
    spec = document["spec"]
    desired = {
        "sourceRevision": subprocess.check_output(["git", "-C", str(vpc_source), "rev-parse", "HEAD"], text=True).strip(),
        "controllerImage": refs["vpc_control_plane"],
        "facadeImage": refs["vpc_facade"],
        "metadataAttestorImage": refs["vpc_metadata_attestor"],
        "endpointAgentImage": refs["vpc_endpoint_agent"],
    }
    if any(spec.get(key) != value for key, value in desired.items()):
        changes.append(Path("deploy/locks/vpc-policy-images.yaml"))
        if args.apply:
            spec.update(desired)
            vpc_lock.write_text(yaml.safe_dump(document, sort_keys=False))

action = "updated" if args.apply else "would update"
for path in changes:
    print(f"{action}: {path}")
print(f"{action} {len(changes)} files")
print("Adjacent services, VPC, and Magnum GitOps manifests were included when their locked checkouts were present; commit each changed repository before acceptance.")
