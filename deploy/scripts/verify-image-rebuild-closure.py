#!/usr/bin/env python3
"""Fail when the empty-Harbor source build graph becomes incomplete."""
from pathlib import Path
import re
import sys

root = Path(__file__).resolve().parents[2]
build = (root / "deploy/scripts/build-images.sh").read_text()
required = {
    "aodh", "ceilometer", "gnocchi", "keystone-oidc", "keycloak",
    "neutron-fwaas", "octavia-ovn", "magnum-capi",
    "magnum-capi-gitops", "magnum-capi-repository-writer",
    "vpc-control-plane", "vpc-facade", "horizon-complete",
    "project-facade", "capo-controller",
}
missing = sorted(name for name in required if name not in build)
if missing:
    raise SystemExit("build-images.sh lacks source builders: " + ", ".join(missing))

bootstrap_dockerfiles = [
    root / "images/horizon-complete/Dockerfile",
    root / "images/keycloak/Dockerfile",
    root / "images/keystone-oidc/Dockerfile",
    root / "images/magnum-capi/Dockerfile",
    root / "images/neutron-fwaas/Dockerfile",
    root / "images/octavia-ovn/Dockerfile",
    root / "images/project-facade/Dockerfile",
]
private_parent = re.compile(r"^\s*(?:FROM|ARG\s+\w+=).*registry\.dcn\.ssu\.ac\.kr", re.M)
errors = []
for path in bootstrap_dockerfiles:
    text = path.read_text()
    if private_parent.search(text):
        errors.append(f"{path.relative_to(root)} has a private bootstrap parent")
    for line in text.splitlines():
        fields = line.split()
        if fields and fields[0].upper() == "FROM":
            parent = fields[1]
            if not parent.startswith("${") and "@sha256:" not in parent:
                errors.append(f"{path.relative_to(root)} has mutable parent {parent}")

horizon = (root / "images/horizon-complete/Dockerfile").read_text()
for token in ("octavia_dashboard", "designatedashboard", "openstack_vpc_dashboard", "project_selfservice_dashboard", "magnum_ui", "magnumclient"):
    if token not in horizon:
        errors.append(f"complete Horizon image lacks {token}")

if errors:
    print("\n".join(errors), file=sys.stderr)
    raise SystemExit(1)
print(f"image-rebuild-closure-ok: {len(required)} custom image families")
