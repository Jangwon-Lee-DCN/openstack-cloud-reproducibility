#!/usr/bin/env python3
"""Render clusterctl-style ${NAME:=default} placeholders after Kustomize."""

import os
import re
import subprocess
from pathlib import Path


root = Path(__file__).resolve().parents[1]
rendered = subprocess.check_output(
    [
        "kubectl",
        "kustomize",
        "--load-restrictor",
        "LoadRestrictionsNone",
        str(root / "overlays" / "poc-ha"),
    ],
    text=True,
)

pattern = re.compile(r"\$\{([A-Z0-9_]+):=([^}]+)\}")

def replace(match):
    return os.environ.get(match.group(1), match.group(2))

result = pattern.sub(replace, rendered)
unresolved = sorted(set(re.findall(r"\$\{[^}]+\}", result)))
if unresolved:
    raise SystemExit(f"unresolved provider placeholders: {unresolved}")
print(result, end="")
