#!/usr/bin/env python3
"""Small, persistent front-end for serialized OpenStack image builds."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import uuid


STATE = Path(os.environ.get("DCN_IMAGE_BUILD_STATE", "/var/lib/dcn-image-build-queue"))
PUEUE = os.environ.get("PUEUE_BIN", "/usr/local/libexec/dcn-image-build-queue/pueue")
CONFIG = os.environ.get("PUEUE_CONFIG_PATH", "/etc/dcn-image-build-queue/pueue.yml")
RUNNER = os.environ.get("DCN_IMAGE_BUILD_RUNNER", "/usr/local/libexec/dcn-image-build-queue/run-image-build")
BUILD_PYTHON_CONFIG = Path("/etc/dcn-image-build-queue/build-python")

COMPONENTS = {
    "horizon-complete": (
        "horizon",
        ("reproducibility", "vpc_dashboard", "telemetry_dashboard", "s3_dashboard", "baremetal_access_dashboard"),
    ),
    "keystone-oidc": ("keystone", ("reproducibility",)),
    "neutron-fwaas": ("neutron", ("reproducibility",)),
    "octavia-ovn": ("octavia", ("reproducibility",)),
    "magnum-capi": ("magnum", ("reproducibility",)),
    "magnum-capi-gitops": ("magnum", ("reproducibility", "magnum_gitops")),
    "magnum-capi-repository-writer": ("magnum", ("reproducibility", "magnum_gitops")),
    "gnocchi": ("platform-images", ("reproducibility",)),
    "ceilometer": ("platform-images", ("reproducibility",)),
    "aodh": ("platform-images", ("reproducibility",)),
    "keycloak": ("platform-images", ("reproducibility",)),
    "project-facade": ("platform-images", ("reproducibility",)),
    "vpc-control-plane": ("platform-images", ("reproducibility", "vpc_control_plane")),
    "vpc-facade": ("platform-images", ("reproducibility", "vpc_control_plane")),
    "loki-tenant-gateway": ("platform-images", ("reproducibility",)),
}


def run(
    args: list[str], *, check: bool = True, cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, check=check, text=True, capture_output=True, env=env)


def pueue(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    # Pueue persists the submitting process environment as part of the task.
    # Never let credentials or session-specific variables enter queue state.
    safe_environment = {
        "HOME": os.environ.get("HOME", "/home/ubuntu"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "PUEUE_CONFIG_PATH": CONFIG,
    }
    python_binary = os.environ.get("PYTHON_BINARY")
    if not python_binary and BUILD_PYTHON_CONFIG.is_file():
        python_binary = BUILD_PYTHON_CONFIG.read_text().strip()
    if python_binary:
        safe_environment["PYTHON_BINARY"] = python_binary
    return run([PUEUE, "--config", CONFIG, *args], check=check, env=safe_environment)


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, sort_keys=True, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def parse_sources(values: list[str]) -> dict[str, dict[str, str]]:
    sources: dict[str, dict[str, str]] = {}
    for value in values:
        if "=" not in value:
            raise SystemExit(f"invalid --source {value!r}; expected NAME=PATH[@REVISION]")
        name, source = value.split("=", 1)
        if not name.replace("_", "").isalnum():
            raise SystemExit(f"invalid source name: {name}")
        path_text, separator, requested_revision = source.rpartition("@")
        path = Path(path_text if separator else source).expanduser().resolve()
        if not (path / ".git").exists() and not (path / "HEAD").exists():
            raise SystemExit(f"not a Git repository: {path}")
        revision = requested_revision if separator else run(["git", "-C", str(path), "rev-parse", "HEAD"]).stdout.strip()
        revision = run(["git", "-C", str(path), "rev-parse", f"{revision}^{{commit}}"]).stdout.strip()
        if len(revision) != 40 or any(c not in "0123456789abcdef" for c in revision):
            raise SystemExit(f"source {name} did not resolve to a full commit SHA")
        if os.environ.get("DCN_IMAGE_BUILD_ALLOW_UNPUSHED") != "1":
            run(["git", "-C", str(path), "fetch", "--quiet", "--prune", "origin"])
            branches = run(["git", "-C", str(path), "branch", "-r", "--contains", revision]).stdout.splitlines()
            if not any(line.strip().startswith("origin/") and " -> " not in line for line in branches):
                raise SystemExit(f"source {name} revision {revision} is not present on an origin branch")
        sources[name] = {"repository": str(path), "revision": revision}
    return sources


def request_files() -> list[Path]:
    return sorted((STATE / "requests").glob("*.json"))


def load_request(identifier: str) -> tuple[Path, dict]:
    candidates = [path for path in request_files() if path.stem == identifier]
    if identifier.isdigit():
        candidates.extend(path for path in request_files() if str(json.loads(path.read_text()).get("task_id")) == identifier)
    unique = list(dict.fromkeys(candidates))
    if len(unique) != 1:
        raise SystemExit(f"request not found or ambiguous: {identifier}")
    return unique[0], json.loads(unique[0].read_text())


def pueue_task(task_id: int) -> dict | None:
    result = pueue("status", "--json", check=False)
    if result.returncode:
        return None
    return json.loads(result.stdout).get("tasks", {}).get(str(task_id))


def effective_status(request: dict) -> str:
    if request.get("status") in {"succeeded", "failed"}:
        return request["status"]
    if "task_id" not in request:
        return request.get("status", "unknown")
    task = pueue_task(request["task_id"])
    if not task:
        return request.get("status", "unknown")
    raw_status = task.get("status", "unknown")
    if isinstance(raw_status, dict) and "Done" in raw_status:
        result = str(raw_status["Done"].get("result", "unknown")).lower()
        return {"success": "succeeded", "failed": "failed", "killed": "killed"}.get(result, result)
    return str(raw_status).lower()


def submit(args: argparse.Namespace) -> int:
    if args.component not in COMPONENTS:
        raise SystemExit(f"unsupported component {args.component}; choose from {', '.join(sorted(COMPONENTS))}")
    group, required = COMPONENTS[args.component]
    sources = parse_sources(args.source)
    missing = sorted(set(required) - set(sources))
    extra = sorted(set(sources) - set(required))
    if missing or extra:
        raise SystemExit(f"source set mismatch; missing={missing}, unexpected={extra}, required={list(required)}")
    fingerprint_input = {"schema": 1, "component": args.component, "sources": sources}
    fingerprint = hashlib.sha256(json.dumps(fingerprint_input, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / "requests").mkdir(exist_ok=True)
    lock_path = STATE / "submit.lock"
    lock_path.touch(mode=0o660, exist_ok=True)
    with lock_path.open("r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for path in request_files():
            previous = json.loads(path.read_text())
            if previous.get("fingerprint") != fingerprint:
                continue
            status = effective_status(previous)
            if status not in {"failed", "killed"}:
                response = {"deduplicated": True, **previous, "status": status}
                print(json.dumps(response, sort_keys=True))
                if args.wait and status != "succeeded":
                    return wait_for(str(previous["task_id"]), quiet=args.quiet)
                return 0
        request_id = str(uuid.uuid4())
        path = STATE / "requests" / f"{request_id}.json"
        request = {
            **fingerprint_input,
            "request_id": request_id,
            "fingerprint": fingerprint,
            "group": group,
            "status": "submitting",
        }
        atomic_json(path, request)
        command = shlex.join([RUNNER, str(path)])
        result = pueue("add", "--print-task-id", "--group", group, "--label", f"{args.component}:{fingerprint[:12]}", command)
        task_id = int(result.stdout.strip())
        request.update({"task_id": task_id, "status": "queued"})
        atomic_json(path, request)
    print(json.dumps(request, sort_keys=True))
    return wait_for(str(task_id), quiet=args.quiet) if args.wait else 0


def wait_for(identifier: str, *, quiet: bool) -> int:
    path, request = load_request(identifier)
    result = pueue("wait", "--status", "success", "--quiet", str(request["task_id"]), check=False)
    request = json.loads(path.read_text())
    status = effective_status(request)
    output = {**request, "status": status}
    print(json.dumps(output, sort_keys=True))
    if status == "succeeded" and request.get("immutable_ref"):
        if not quiet:
            print(request["immutable_ref"])
        return 0
    return result.returncode or 1


def show(identifier: str) -> int:
    _, request = load_request(identifier)
    print(json.dumps({**request, "status": effective_status(request)}, sort_keys=True, indent=2))
    return 0


def logs(identifier: str) -> int:
    _, request = load_request(identifier)
    result = pueue("log", str(request["task_id"]), check=False)
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    return result.returncode


def cancel(identifier: str) -> int:
    path, request = load_request(identifier)
    result = pueue("kill", str(request["task_id"]), check=False)
    request.update({"status": "killed"})
    atomic_json(path, request)
    return result.returncode


def health() -> int:
    result = pueue("status", "--json", check=False)
    if result.returncode:
        sys.stderr.write(result.stderr)
        return result.returncode
    state = json.loads(result.stdout)
    groups = state.get("groups", {})
    expected = {value[0] for value in COMPONENTS.values()}
    missing = sorted(expected - set(groups))
    if missing:
        print(json.dumps({"status": "unhealthy", "missing_groups": missing}))
        return 1
    print(json.dumps({"status": "ok", "groups": sorted(expected)}))
    return 0


def queue_view(*, include_finished: bool = False) -> int:
    """Print a stable, human-readable view without exposing raw Pueue state."""
    requests = []
    for path in request_files():
        request = json.loads(path.read_text())
        request["status"] = effective_status(request)
        requests.append(request)
    requests.sort(key=lambda item: int(item.get("task_id", -1)))
    if not include_finished:
        requests = [item for item in requests if item["status"] not in {"succeeded", "failed", "killed"}]
    if not requests:
        print("Image build queue is empty.")
        return 0

    columns = ("TASK", "GROUP", "COMPONENT", "STATUS", "REQUEST")
    rows = [
        (
            str(item.get("task_id", "-")),
            item.get("group", "-"),
            item.get("component", "-"),
            item["status"],
            item.get("request_id", "-")[:12],
        )
        for item in requests
    ]
    widths = [max(len(columns[index]), *(len(row[index]) for row in rows)) for index in range(len(columns))]
    print("  ".join(value.ljust(widths[index]) for index, value in enumerate(columns)))
    for row in rows:
        print("  ".join(value.ljust(widths[index]) for index, value in enumerate(row)))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="dcn-image-build")
    sub = parser.add_subparsers(dest="command", required=True)
    submit_parser = sub.add_parser("submit")
    submit_parser.add_argument("--component", required=True)
    submit_parser.add_argument("--source", action="append", default=[], metavar="NAME=PATH[@REVISION]")
    submit_parser.add_argument("--wait", action="store_true")
    submit_parser.add_argument("--quiet", action="store_true")
    for command in ("status", "wait", "log", "cancel"):
        command_parser = sub.add_parser(command)
        command_parser.add_argument("request")
        if command == "wait":
            command_parser.add_argument("--quiet", action="store_true")
    sub.add_parser("list")
    queue_parser = sub.add_parser("queue", help="show queued and running image builds")
    queue_parser.add_argument("--all", action="store_true", help="include completed and failed builds")
    sub.add_parser("health")
    args = parser.parse_args()
    if args.command == "submit":
        return submit(args)
    if args.command == "status":
        return show(args.request)
    if args.command == "wait":
        return wait_for(args.request, quiet=args.quiet)
    if args.command == "log":
        return logs(args.request)
    if args.command == "cancel":
        return cancel(args.request)
    if args.command == "list":
        for path in request_files():
            request = json.loads(path.read_text())
            print(json.dumps({**request, "status": effective_status(request)}, sort_keys=True))
        return 0
    if args.command == "queue":
        return queue_view(include_finished=args.all)
    return health()


if __name__ == "__main__":
    raise SystemExit(main())
