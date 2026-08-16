#!/usr/bin/env python3
"""Fail closed unless portable source is the exact clean site-approved revision."""

import subprocess
import sys
from pathlib import Path

import yaml


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def verify(portable: Path, site: Path) -> str:
    portable = portable.resolve()
    site = site.resolve()
    if git(site, "branch", "--show-current") != "main":
        raise RuntimeError("site source must be on main")
    if git(site, "status", "--porcelain"):
        raise RuntimeError("site source must be clean")
    if git(portable, "status", "--porcelain"):
        raise RuntimeError("portable source must be clean")
    revision = git(portable, "rev-parse", "HEAD")
    approved = []
    for relative in ("automation/development-repositories.lock.yaml",
                     "automation/repositories.lock.yaml"):
        lock = yaml.safe_load((site / relative).read_text(encoding="utf-8"))
        approved.append(lock["repositories"]["reproducibility"]["revision"])
    if approved != [revision, revision]:
        raise RuntimeError("portable HEAD does not match both site reproducibility locks")
    return revision


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: verify-cloudkitty-source-lock.py PORTABLE_ROOT SITE_ROOT")
    try:
        print(verify(Path(sys.argv[1]), Path(sys.argv[2])))
    except (KeyError, OSError, subprocess.CalledProcessError, RuntimeError) as exc:
        raise SystemExit(str(exc)) from exc
