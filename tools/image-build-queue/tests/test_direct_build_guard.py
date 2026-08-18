from pathlib import Path
import os
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]


class DirectBuildGuardTests(unittest.TestCase):
    def test_active_queue_rejects_direct_build(self):
        with tempfile.TemporaryDirectory() as temporary:
            binary_directory = Path(temporary)
            systemctl = binary_directory / "systemctl"
            systemctl.write_text("#!/usr/bin/env sh\nexit 0\n")
            systemctl.chmod(0o755)
            result = subprocess.run(
                [str(ROOT / "deploy/scripts/build-images.sh")],
                env={**os.environ, "PATH": f"{binary_directory}:{os.environ['PATH']}"},
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("direct image builds are disabled", result.stderr)

    def test_queue_runner_passes_guard(self):
        with tempfile.TemporaryDirectory() as temporary:
            binary_directory = Path(temporary)
            systemctl = binary_directory / "systemctl"
            systemctl.write_text("#!/usr/bin/env sh\nexit 0\n")
            systemctl.chmod(0o755)
            # Passing the guard continues into normal preflight and therefore
            # fails later for a deliberately missing command/path, not at the
            # queue guard.
            result = subprocess.run(
                [str(ROOT / "deploy/scripts/build-images.sh")],
                env={
                    **os.environ,
                    "PATH": str(binary_directory),
                    "DCN_IMAGE_BUILD_QUEUE_TASK": "test-request",
                },
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 2)
            self.assertNotIn("direct image builds are disabled", result.stderr)


if __name__ == "__main__":
    unittest.main()
