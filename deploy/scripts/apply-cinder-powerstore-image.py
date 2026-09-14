#!/usr/bin/env python3
"""Pin the reviewed PowerStore compatibility image for cinder-volume only."""

import argparse
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
VALUES = ROOT / "deploy/values/site/cinder.yaml"
EXPECTED_REPOSITORY = "registry.dcn.ssu.ac.kr/openstack/cinder"


def apply(reference: str, *, write: bool) -> bool:
    if not re.fullmatch(
        re.escape(EXPECTED_REPOSITORY) + r":[a-z0-9][a-z0-9.-]*@sha256:[a-f0-9]{64}",
        reference,
    ):
        raise ValueError("Cinder image must use the private repository, an immutable tag and sha256 digest")
    source = VALUES.read_text()
    updated, count = re.subn(
        r"(?m)^(\s+cinder_volume:)\s+\S+$",
        rf"\1 {reference}",
        source,
    )
    if count != 1:
        raise RuntimeError(f"expected one cinder_volume pin, found {count}")
    if write and updated != source:
        VALUES.write_text(updated)
    return updated != source


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("reference")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    changed = apply(args.reference, write=args.apply)
    print(("updated" if args.apply else "would update") if changed else "already pinned")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
