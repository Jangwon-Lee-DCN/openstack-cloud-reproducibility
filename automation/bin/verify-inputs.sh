#!/usr/bin/env bash
set -euo pipefail

root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
allow_dirty=${ALLOW_DIRTY_REBUILD_INPUTS:-0}

for command in git python3 sha256sum tar; do
  command -v "$command" >/dev/null || {
    echo "missing command: $command" >&2
    exit 1
  }
done

if [[ "$allow_dirty" != "1" ]] && [[ -n "$(git -C "$root" status --porcelain)" ]]; then
  echo "reproducibility repository is dirty; use an accepted immutable commit" >&2
  exit 1
fi

python3 - "$root" <<'PY'
import hashlib
import pathlib
import sys
import tarfile
import yaml

root = pathlib.Path(sys.argv[1])
lock = yaml.safe_load((root / "release-lock.yaml").read_text())
errors = []
seen = set()

for release in lock["spec"]["releases"]:
    name = release["name"]
    if name in seen:
        errors.append(f"duplicate release: {name}")
        continue
    seen.add(name)
    package = root / release["package"]
    if not package.is_file():
        errors.append(f"{name}: missing package {package.relative_to(root)}")
        continue
    actual = hashlib.sha256(package.read_bytes()).hexdigest()
    if actual != release["sha256"]:
        errors.append(f"{name}: sha256 mismatch, expected {release['sha256']}, got {actual}")
    try:
        with tarfile.open(package, "r:gz") as archive:
            chart_member = next(m for m in archive.getmembers() if m.name.endswith("/Chart.yaml"))
            chart = yaml.safe_load(archive.extractfile(chart_member))
        if chart.get("name") != release["chart"]:
            errors.append(f"{name}: chart name mismatch")
        if str(chart.get("version")) != str(release["chartVersion"]):
            errors.append(f"{name}: chart version mismatch")
    except Exception as exc:
        errors.append(f"{name}: unreadable chart package: {exc}")
    for key in ("valuesSnapshot", "valuesFile", "secretsFile"):
        value = release.get(key)
        if value and not (root / value).is_file():
            errors.append(f"{name}: missing {key} {value}")

if errors:
    print("\n".join(errors), file=sys.stderr)
    raise SystemExit(1)
print(f"verified {len(seen)} pinned Helm releases")
PY

echo "immutable rebuild input verification passed"
