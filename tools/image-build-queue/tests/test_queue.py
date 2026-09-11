from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock
from contextlib import redirect_stdout
from io import StringIO


ROOT = Path(__file__).resolve().parents[1]


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


queue = load("dcn_image_build", "dcn_image_build.py")
runner = load("run_image_build", "run_image_build.py")


class QueueTests(unittest.TestCase):
    def test_cinder_compatibility_image_is_serialized(self):
        self.assertEqual(
            queue.COMPONENTS["cinder-powerstore-legacy-api"],
            ("cinder", ("reproducibility",)),
        )
        source = (ROOT.parent.parent / "deploy/scripts/build-images.sh").read_text()
        self.assertIn("selected cinder-powerstore-legacy-api", source)
        groups = (ROOT / "init-groups").read_text()
        self.assertIn('for group in $("$CLI" groups)', groups)
        with redirect_stdout(StringIO()) as output:
            self.assertEqual(queue.group_names(), 0)
        self.assertIn("cinder", output.getvalue().splitlines())

    def test_gpu_profiles_are_version_named_and_serialized(self):
        expected = {
            "ubuntu-22.04-cuda-11.8", "ubuntu-22.04-cuda-12.4",
            "ubuntu-22.04-cuda-12.8", "ubuntu-24.04-cuda-12.8",
            "ubuntu-24.04-cuda-12.9", "ubuntu-24.04-cuda-13.0",
        }
        profiles = json.loads((ROOT.parent.parent / "images/gpu-runtime/profiles.json").read_text())
        nccl = json.loads((ROOT.parent.parent / "images/gpu-runtime/nccl-packages.json").read_text())
        self.assertEqual(expected, set(profiles))
        self.assertEqual(expected, set(nccl))
        self.assertFalse(any("legacy" in name for name in profiles))
        for name in expected:
            self.assertEqual(queue.COMPONENTS[name], ("glance-images", ("reproducibility",)))
        builder = (ROOT.parent.parent / "images/gpu-runtime/build.sh").read_text()
        self.assertIn("ip address replace 169.254.2.15/16", builder)
        self.assertIn("nameserver 169.254.2.3", builder)
        self.assertEqual(builder.count("--run-command \"$guest_network; curl"), 1)
        self.assertIn("stub-resolv.conf", builder)
        self.assertIn("virt-resize --expand /dev/sda1", builder)
        self.assertIn("DCN_GPU_BASE_CACHE", builder)

    def test_disk_artifact_is_checksum_verified_and_persisted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            artifact = workspace / "image.qcow2"
            artifact.write_bytes(b"disk-image")
            digest = "sha256:" + __import__("hashlib").sha256(b"disk-image").hexdigest()
            result = workspace / "result.env"
            result.write_text(f"image={artifact}@{digest}\n")
            ref, actual = runner.persist_disk_artifact(workspace, result, root, "request-1")
            self.assertEqual(actual, digest)
            self.assertTrue(ref.startswith(f"file://{root}/artifacts/request-1/image.qcow2@"))

    def test_baremetal_service_and_dashboard_sources_are_mandatory(self):
        self.assertEqual(
            queue.COMPONENTS["baremetal-access-service"][1],
            ("reproducibility", "netbox_ironic_controller"),
        )
        self.assertIn(
            "baremetal_access_dashboard", queue.COMPONENTS["horizon-complete"][1],
        )

    def test_support_api_and_horizon_require_support_source(self):
        self.assertEqual(
            queue.COMPONENTS["support-api"][1],
            ("reproducibility", "support_dashboard"),
        )
        self.assertIn("support_dashboard", queue.COMPONENTS["horizon-complete"][1])
        source = (ROOT.parent.parent / "deploy/scripts/build-images.sh").read_text()
        self.assertIn("selected support-api", source)
        self.assertIn("openstack_support_dashboard.whl", source)

    def test_flavor_catalog_requires_its_service_source(self):
        self.assertEqual(
            ("reproducibility", "cloud_services"),
            queue.COMPONENTS["flavor-catalog"][1],
        )
        source = (ROOT.parent.parent / "deploy/scripts/build-images.sh").read_text()
        self.assertIn("selected flavor-catalog", source)
        self.assertIn("CLOUD_SERVICES_REPO", source)

    def test_service_supplies_a_build_capable_python(self):
        service = (ROOT / "dcn-image-build-queue.service").read_text()
        installer = (ROOT / "install.sh").read_text()
        self.assertIn("Environment=PYTHON_BINARY=@BUILD_PYTHON@", service)
        self.assertIn("Environment=LIBGUESTFS_CACHEDIR=/var/lib/dcn-image-build-queue/libguestfs", service)
        self.assertIn("Environment=SUPERMIN_KERNEL=/var/lib/dcn-image-build-queue/kernels/vmlinuz-@KERNEL_VERSION@", service)
        self.assertIn("Environment=SUPERMIN_MODULES=/var/lib/dcn-image-build-queue/kernels/modules-@KERNEL_VERSION@", service)
        self.assertIn("-c 'import build'", installer)
        self.assertIn('s#@BUILD_PYTHON@#$build_python#g', installer)
        self.assertIn("systemctl restart dcn-image-build-queue.service", installer)
        self.assertIn("/var/lib/dcn-image-build-queue/libguestfs", installer)
        self.assertIn('"/boot/vmlinuz-$kernel_version"', installer)
        self.assertIn('cp -aT "/lib/modules/$kernel_version"', installer)

    def test_pueue_environment_is_allow_listed(self):
        captured = {}

        def fake_run(args, **kwargs):
            captured.update(kwargs["env"])
            return subprocess.CompletedProcess(args, 0, "{}", "")

        with mock.patch.dict(os.environ, {
            "GH_TOKEN": "must-not-leak",
            "SOPS_AGE_KEY_FILE": "/secret",
            "PYTHON_BINARY": "/opt/dcn-build/bin/python",
        }), mock.patch.object(queue, "run", fake_run):
            queue.pueue("status", "--json")
        self.assertNotIn("GH_TOKEN", captured)
        self.assertNotIn("SOPS_AGE_KEY_FILE", captured)
        self.assertEqual(captured["PUEUE_CONFIG_PATH"], queue.CONFIG)
        self.assertEqual(captured["LIBGUESTFS_CACHEDIR"], str(queue.STATE / "libguestfs"))
        self.assertEqual(captured["SUPERMIN_KERNEL"], str(queue.STATE / "kernels" / f"vmlinuz-{os.uname().release}"))
        self.assertEqual(captured["SUPERMIN_MODULES"], str(queue.STATE / "kernels" / f"modules-{os.uname().release}"))
        self.assertEqual(captured["DCN_GPU_BASE_CACHE"], str(queue.STATE / "cache" / "ubuntu"))
        self.assertEqual(captured["PYTHON_BINARY"], "/opt/dcn-build/bin/python")

    def test_pueue_reads_build_python_when_submitter_environment_is_empty(self):
        captured = {}

        def fake_run(args, **kwargs):
            captured.update(kwargs["env"])
            return subprocess.CompletedProcess(args, 0, "{}", "")

        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "build-python"
            config.write_text("/opt/dcn-build/bin/python\n")
            with mock.patch.dict(os.environ, {}, clear=True), \
                    mock.patch.object(queue, "BUILD_PYTHON_CONFIG", config), \
                    mock.patch.object(queue, "run", fake_run):
                queue.pueue("status", "--json")
        self.assertEqual(captured["PYTHON_BINARY"], "/opt/dcn-build/bin/python")

    def test_pueue_v4_done_status_is_normalized(self):
        request = {"task_id": 7, "status": "running"}
        task = {"status": {"Done": {"result": "Success"}}}
        with mock.patch.object(queue, "pueue_task", return_value=task):
            self.assertEqual(queue.effective_status(request), "succeeded")

    def test_queue_view_defaults_to_active_requests(self):
        requests = [
            {"task_id": 2, "group": "horizon", "component": "horizon-complete", "request_id": "active-request", "status": "running"},
            {"task_id": 1, "group": "keystone", "component": "keystone-oidc", "request_id": "done-request", "status": "succeeded"},
        ]
        with tempfile.TemporaryDirectory() as temporary, \
                mock.patch.object(queue, "STATE", Path(temporary)), \
                mock.patch.object(queue, "effective_status", side_effect=lambda request: request["status"]):
            request_dir = Path(temporary) / "requests"
            request_dir.mkdir()
            for index, request in enumerate(requests):
                (request_dir / f"{index}.json").write_text(json.dumps(request))
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(queue.queue_view(), 0)
        self.assertIn("horizon-complete", output.getvalue())
        self.assertNotIn("keystone-oidc", output.getvalue())

    def test_queue_view_reports_an_empty_queue(self):
        with tempfile.TemporaryDirectory() as temporary, \
                mock.patch.object(queue, "STATE", Path(temporary)):
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(queue.queue_view(), 0)
        self.assertEqual(output.getvalue(), "Image build queue is empty.\n")

    def test_runner_returns_exact_immutable_digest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = self.make_repository(root / "repository", success=True)
            request_path = root / "requests" / "request.json"
            request_path.parent.mkdir()
            request = {
                "component": "keystone-oidc",
                "fingerprint": "1" * 64,
                "sources": {"reproducibility": {"repository": str(repository), "revision": self.head(repository)}},
                "status": "queued",
            }
            request_path.write_text(json.dumps(request))
            self.assertEqual(runner.execute(request_path), 0)
            result = json.loads(request_path.read_text())
            self.assertEqual(result["status"], "succeeded")
            self.assertEqual(result["digest"], "sha256:" + "a" * 64)
            self.assertTrue(result["immutable_ref"].endswith("@sha256:" + "a" * 64))

    def test_clone_uses_origin_instead_of_sharing_a_source_worktree(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bare = root / "origin.git"
            subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
            source = self.make_repository(root / "source", success=True)
            subprocess.run(["git", "-C", str(source), "remote", "add", "origin", str(bare)], check=True)
            subprocess.run(["git", "-C", str(source), "push", "-q", "origin", "HEAD:main"], check=True)
            destination = root / "clone"
            runner.clone_at({"repository": str(source), "revision": self.head(source)}, destination)
            self.assertEqual(self.head(source), self.head(destination))

    def test_runner_fails_closed_without_digest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = self.make_repository(root / "repository", success=False)
            request_path = root / "requests" / "request.json"
            request_path.parent.mkdir()
            request_path.write_text(json.dumps({
                "component": "keystone-oidc",
                "fingerprint": "2" * 64,
                "sources": {"reproducibility": {"repository": str(repository), "revision": self.head(repository)}},
                "status": "queued",
            }))
            self.assertEqual(runner.execute(request_path), 1)
            result = json.loads(request_path.read_text())
            self.assertEqual(result["status"], "failed")
            self.assertNotIn("digest", result)

    @staticmethod
    def head(repository: Path) -> str:
        return subprocess.check_output(["git", "-C", str(repository), "rev-parse", "HEAD"], text=True).strip()

    @staticmethod
    def make_repository(path: Path, *, success: bool) -> Path:
        path.mkdir()
        subprocess.run(["git", "init", "-q", str(path)], check=True)
        subprocess.run(["git", "-C", str(path), "config", "user.email", "queue-test@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(path), "config", "user.name", "Queue Test"], check=True)
        script = path / "deploy" / "scripts" / "build-images.sh"
        script.parent.mkdir(parents=True)
        if success:
            script.write_text("#!/usr/bin/env bash\nset -eu\nprintf 'keystone_oidc=registry.invalid/openstack/keystone:source-test@sha256:%064d\\n' 0 | tr 0 a >\"$RESULT_FILE\"\n")
        else:
            script.write_text("#!/usr/bin/env bash\nset -eu\n: >\"$RESULT_FILE\"\n")
        script.chmod(0o755)
        subprocess.run(["git", "-C", str(path), "add", "."], check=True)
        subprocess.run(["git", "-C", str(path), "commit", "-qm", "fixture"], check=True)
        return path


if __name__ == "__main__":
    unittest.main()
