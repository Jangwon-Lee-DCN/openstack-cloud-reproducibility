#!/usr/bin/env python3
"""Create a collision-resistant Kubernetes name for a source image build."""

import hashlib
import re
import sys


def build_name(component: str, build_id: str) -> str:
    normalized = re.sub(r"[^a-z0-9-]+", "-", component.lower()).strip("-") or "image"
    identity = hashlib.sha256(component.encode()).hexdigest()[:8]
    suffix = re.sub(r"[^a-z0-9-]+", "-", build_id.lower()).strip("-")[:20] or "build"
    # 14-char prefix + separators + 18-char stem + 8-char identity + 20-char
    # build suffix = at most Kubernetes' 63-character DNS label limit.
    return f"source-rebuild-{normalized[:18]}-{identity}-{suffix}"


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: kubernetes-image-build-name.py COMPONENT BUILD_ID")
    print(build_name(sys.argv[1], sys.argv[2]))
