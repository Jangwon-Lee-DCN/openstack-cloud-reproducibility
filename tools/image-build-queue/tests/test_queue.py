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
    def test_service_supplies_a_build_capable_python(self):
        service = (ROOT / "dcn-image-build-queue.service").read_text()
        installer = (ROOT / "install.sh").read_text()
        self.assertIn("Environment=PYTHON_BINARY=@BUILD_PYTHON@", service)
        self.assertIn("-c 'import build'", installer)
        self.assertIn('s#@BUILD_PYTHON@#$build_python#g', installer)

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
