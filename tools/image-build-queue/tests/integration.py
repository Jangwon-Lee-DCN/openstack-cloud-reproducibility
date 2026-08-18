#!/usr/bin/env python3
"""Pueue v4 integration acceptance using isolated temporary state."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
PUEUE_VERSION = "v4.0.4"
CHECKSUMS = {
    "pueue": "c1b10d7e4e62211075ddd0e1dc3e8cbfc5a43d662cb3be7402a28504e23fcb51",
    "pueued": "5afeff6adbafb909e8d54e2caff158e6966c2adffa2c09e60fd631cc51b60390",
}


def command(args: list[str], *, env=None, check=True, capture=True):
    return subprocess.run(args, env=env, check=check, text=True, capture_output=capture)


def download(binary: str, destination: Path) -> None:
    url = f"https://github.com/Nukesor/pueue/releases/download/{PUEUE_VERSION}/{binary}-x86_64-unknown-linux-musl"
    with urllib.request.urlopen(url) as response, destination.open("wb") as stream:
        shutil.copyfileobj(response, stream)
    actual = hashlib.sha256(destination.read_bytes()).hexdigest()
    if actual != CHECKSUMS[binary]:
        raise RuntimeError(f"{binary} checksum mismatch: {actual}")
    destination.chmod(0o755)


def make_repository(path: Path) -> tuple[Path, str]:
    bare = path.with_suffix(".git")
    command(["git", "init", "-q", "--bare", str(bare)])
    command(["git", "init", "-q", str(path)])
    command(["git", "-C", str(path), "config", "user.email", "queue-integration@example.invalid"])
    command(["git", "-C", str(path), "config", "user.name", "Queue Integration"])
    command(["git", "-C", str(path), "remote", "add", "origin", str(bare)])
    marker = path / "marker"
    marker.write_text("one\n")
    command(["git", "-C", str(path), "add", "."])
    command(["git", "-C", str(path), "commit", "-qm", "one"])
    command(["git", "-C", str(path), "push", "-q", "-u", "origin", "HEAD:main"])
    return path, command(["git", "-C", str(path), "rev-parse", "HEAD"]).stdout.strip()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="dcn-image-queue-integration.") as temporary:
        root = Path(temporary)
        binary_dir, runtime, data, state = root / "bin", root / "run", root / "pueue-data", root / "state"
        for directory in (binary_dir, runtime, data, state):
            directory.mkdir()
        pueue, pueued = binary_dir / "pueue", binary_dir / "pueued"
        download("pueue", pueue)
        download("pueued", pueued)
        config = root / "pueue.yml"
        config.write_text((ROOT / "pueue.yml").read_text()
            .replace("/var/lib/dcn-image-build-queue/pueue", str(data))
            .replace("/run/dcn-image-build-queue", str(runtime))
            .replace("/etc/dcn-image-build-queue/pueue_aliases.yml", str(root / "aliases.yml")))
        trace = root / "trace"
        fake_runner = root / "fake-runner.py"
        fake_runner.write_text(f'''#!/usr/bin/env python3
import json, os, pathlib, time, sys
p=pathlib.Path(sys.argv[1]); r=json.loads(p.read_text()); marker=r["sources"]["reproducibility"]["revision"][:8]
with open({str(trace)!r}, "a") as f: f.write("start "+marker+"\\n")
time.sleep(1.5)
r.update(status="succeeded", digest="sha256:"+marker.ljust(64,"0"), immutable_ref="registry.invalid/test@sha256:"+marker.ljust(64,"0"))
t=p.with_suffix(".tmp"); t.write_text(json.dumps(r)); os.replace(t,p)
with open({str(trace)!r}, "a") as f: f.write("end "+marker+"\\n")
''')
        fake_runner.chmod(0o755)
        repository, first = make_repository(root / "source")
        daemon_log = (root / "daemon.log").open("w")
        daemon = subprocess.Popen([str(pueued), "-c", str(config)], stdout=daemon_log, stderr=subprocess.STDOUT)
        try:
            socket = runtime / "pueue.socket"
            for _ in range(100):
                if socket.exists():
                    break
                time.sleep(0.05)
            else:
                raise RuntimeError("Pueue socket did not appear")
            base_env = {
                **os.environ,
                "PUEUE_BIN": str(pueue),
                "PUEUE_CONFIG_PATH": str(config),
                "DCN_IMAGE_BUILD_STATE": str(state),
                "DCN_IMAGE_BUILD_RUNNER": str(fake_runner),
                "DCN_TEST_SECRET": "must-not-enter-pueue",
            }
            for group in ("keystone", "horizon", "nova", "neutron", "octavia", "magnum", "platform-images"):
                command([str(pueue), "-c", str(config), "group", "add", "--parallel", "1", group])
            cli = str(ROOT / "dcn_image_build.py")
            first_submit = json.loads(command([cli, "submit", "--component", "keystone-oidc", "--source", f"reproducibility={repository}@{first}"], env=base_env).stdout)
            marker = repository / "marker"
            marker.write_text("two\n")
            command(["git", "-C", str(repository), "add", "."])
            command(["git", "-C", str(repository), "commit", "-qm", "two"])
            command(["git", "-C", str(repository), "push", "-q", "origin", "HEAD:main"])
            second = command(["git", "-C", str(repository), "rev-parse", "HEAD"]).stdout.strip()
            second_submit = json.loads(command([cli, "submit", "--component", "keystone-oidc", "--source", f"reproducibility={repository}@{second}"], env=base_env).stdout)
            command([cli, "wait", str(first_submit["task_id"]), "--quiet"], env=base_env)
            command([cli, "wait", str(second_submit["task_id"]), "--quiet"], env=base_env)
            expected = [f"start {first[:8]}", f"end {first[:8]}", f"start {second[:8]}", f"end {second[:8]}"]
            if trace.read_text().splitlines() != expected:
                raise RuntimeError(f"FIFO violation: {trace.read_text()!r}")
            deduplicated = json.loads(command([cli, "submit", "--component", "keystone-oidc", "--source", f"reproducibility={repository}@{first}"], env=base_env).stdout.splitlines()[0])
            if not deduplicated.get("deduplicated") or deduplicated["task_id"] != first_submit["task_id"]:
                raise RuntimeError("deduplication did not reuse the first task")
            trace.write_text("")
            marker.write_text("parallel\n")
            command(["git", "-C", str(repository), "add", "."])
            command(["git", "-C", str(repository), "commit", "-qm", "parallel"])
            command(["git", "-C", str(repository), "push", "-q", "origin", "HEAD:main"])
            parallel_revision = command(["git", "-C", str(repository), "rev-parse", "HEAD"]).stdout.strip()
            parallel_a = json.loads(command([cli, "submit", "--component", "keystone-oidc", "--source", f"reproducibility={repository}@{parallel_revision}"], env=base_env).stdout)
            horizon_sources = []
            for source_name in ("reproducibility", "vpc_dashboard", "telemetry_dashboard", "s3_dashboard"):
                horizon_sources.extend(["--source", f"{source_name}={repository}@{parallel_revision}"])
            parallel_b = json.loads(command([cli, "submit", "--component", "horizon-complete", *horizon_sources], env=base_env).stdout)
            command([cli, "wait", str(parallel_a["task_id"]), "--quiet"], env=base_env)
            command([cli, "wait", str(parallel_b["task_id"]), "--quiet"], env=base_env)
            parallel_trace = trace.read_text().splitlines()
            if len(parallel_trace) != 4 or not all(line.startswith("start ") for line in parallel_trace[:2]):
                raise RuntimeError(f"independent groups did not overlap: {parallel_trace!r}")
            pueue_state = json.loads(command([str(pueue), "-c", str(config), "status", "--json"]).stdout)
            for task in pueue_state["tasks"].values():
                envs = task.get("envs", {})
                env_names = {entry.split("=", 1)[0] for entry in envs} if isinstance(envs, list) else set(envs)
                env_names.discard("")
                env_names = {name for name in env_names if name.strip()}
                unexpected = env_names - {
                    "HOME", "LANG", "LC_ALL", "PATH", "PUEUE_CONFIG_PATH",
                    "PUEUE_GROUP", "PUEUE_WORKER_ID", "PYTHON_BINARY",
                }
                if unexpected:
                    raise RuntimeError(f"submission environment leaked into Pueue state: {sorted(unexpected)}; raw={envs!r}")
            command([str(pueue), "-c", str(config), "pause", "--group", "keystone"])
            marker.write_text("three\n")
            command(["git", "-C", str(repository), "add", "."])
            command(["git", "-C", str(repository), "commit", "-qm", "three"])
            command(["git", "-C", str(repository), "push", "-q", "origin", "HEAD:main"])
            third = command(["git", "-C", str(repository), "rev-parse", "HEAD"]).stdout.strip()
            third_submit = json.loads(command([cli, "submit", "--component", "keystone-oidc", "--source", f"reproducibility={repository}@{third}"], env=base_env).stdout)
            daemon.terminate(); daemon.wait(timeout=10)
            daemon = subprocess.Popen([str(pueued), "-c", str(config)], stdout=daemon_log, stderr=subprocess.STDOUT)
            for _ in range(100):
                if command([str(pueue), "-c", str(config), "status", "--json"], check=False).returncode == 0:
                    break
                time.sleep(0.05)
            command([str(pueue), "-c", str(config), "start", "--group", "keystone"])
            command([cli, "wait", str(third_submit["task_id"]), "--quiet"], env=base_env)
            print("image build queue integration acceptance passed")
            return 0
        finally:
            if daemon.poll() is None:
                daemon.terminate()
                daemon.wait(timeout=10)
            daemon_log.close()


if __name__ == "__main__":
    raise SystemExit(main())
