#!/usr/bin/env python3
"""Execute one validated image request and persist its immutable result."""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


DISK_COMPONENT_PREFIX = "ubuntu-"


def persist_disk_artifact(workspace: Path, result_file: Path, state: Path, request_id: str) -> tuple[str, str]:
    rows = [line.strip() for line in result_file.read_text().splitlines() if line.strip()]
    if len(rows) != 1 or "=" not in rows[0]:
        raise RuntimeError(f"expected exactly one disk result, got: {rows}")
    _, value = rows[0].split("=", 1)
    if "@sha256:" not in value:
        raise RuntimeError("disk result does not contain sha256 digest")
    raw_path, digest = value.rsplit("@", 1)
    artifact = Path(raw_path).resolve()
    if workspace.resolve() not in artifact.parents or not artifact.is_file():
        raise RuntimeError("disk artifact is absent or outside the build workspace")
    checksum = hashlib.sha256()
    with artifact.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    actual = "sha256:" + checksum.hexdigest()
    if actual != digest:
        raise RuntimeError(f"disk artifact checksum mismatch: declared={digest} actual={actual}")
    destination_dir = state / "artifacts" / request_id
    destination_dir.mkdir(parents=True, exist_ok=False)
    destination = destination_dir / artifact.name
    shutil.move(str(artifact), destination)
    return f"file://{destination}@{digest}", digest


def atomic_json(path: Path, value: dict) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, sort_keys=True, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def clone_at(source: dict[str, str], destination: Path) -> None:
    subprocess.run(["git", "clone", "--quiet", "--shared", "--no-checkout", source["repository"], str(destination)], check=True)
    subprocess.run(["git", "-C", str(destination), "checkout", "--quiet", "--detach", source["revision"]], check=True)


def execute(path: Path) -> int:
    request = json.loads(path.read_text())
    request["status"] = "running"
    atomic_json(path, request)
    workspace = Path(tempfile.mkdtemp(prefix="dcn-image-build.", dir=path.parent.parent))
    try:
        checkouts: dict[str, Path] = {}
        for name, source in request["sources"].items():
            destination = workspace / name
            clone_at(source, destination)
            checkouts[name] = destination
        repro = checkouts["reproducibility"]
        result_file = workspace / "result.env"
        environment = {
            **os.environ,
            "BUILD_COMPONENTS": request["component"],
            "BUILD_ID": request["fingerprint"][:20],
            "DCN_IMAGE_BUILD_QUEUE_TASK": request.get("request_id", "test-request"),
            "RESULT_FILE": str(result_file),
        }
        mappings = {
            "vpc_dashboard": "VPC_DASHBOARD_REPO",
            "telemetry_dashboard": "TELEMETRY_DASHBOARD_REPO",
            "s3_dashboard": "S3_DASHBOARD_REPO",
            "baremetal_access_dashboard": "BAREMETAL_ACCESS_DASHBOARD_REPO",
            "support_dashboard": "SUPPORT_DASHBOARD_REPO",
            "magnum_gitops": "MAGNUM_GITOPS_REPO",
            "vpc_control_plane": "VPC_CONTROL_PLANE_REPO",
            "netbox_ironic_controller": "NETBOX_IRONIC_CONTROLLER_REPO",
            "cloud_services": "CLOUD_SERVICES_REPO",
        }
        for name, variable in mappings.items():
            if name in checkouts:
                environment[variable] = str(checkouts[name])
        if request["component"].startswith(DISK_COMPONENT_PREFIX) and "-cuda-" in request["component"]:
            subprocess.run([
                str(repro / "images/gpu-runtime/build.sh"),
                request["component"], str(workspace / "output"),
            ], cwd=repro, env=environment, check=True)
            immutable_ref, digest = persist_disk_artifact(
                workspace, result_file, path.parent.parent,
                request.get("request_id", "test-request"),
            )
            request.update({"status": "succeeded", "immutable_ref": immutable_ref, "digest": digest})
            atomic_json(path, request)
            print(immutable_ref)
            return 0
        subprocess.run([str(repro / "deploy/scripts/build-images.sh")], cwd=repro, env=environment, check=True)
        rows = [line.strip() for line in result_file.read_text().splitlines() if line.strip()]
        if len(rows) != 1 or "=" not in rows[0] or "@sha256:" not in rows[0]:
            raise RuntimeError(f"expected exactly one immutable result, got: {rows}")
        _, immutable_ref = rows[0].split("=", 1)
        request.update({"status": "succeeded", "immutable_ref": immutable_ref, "digest": immutable_ref.rsplit("@", 1)[1]})
        atomic_json(path, request)
        print(immutable_ref)
        return 0
    except Exception as exc:
        request.update({"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
        atomic_json(path, request)
        print(request["error"], file=sys.stderr)
        return 1
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: run-image-build REQUEST.json")
    raise SystemExit(execute(Path(sys.argv[1]).resolve()))
