"""Pinned-wheel JavaScript regression, not browser or production acceptance."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]
WHEEL_SHA = '93139ab8e6401a7069fa22b0f39deecc9defd73eed62f0441b0923926914f72a'


class WorkflowInitializationTest(unittest.TestCase):
    def setUp(self):
        wheel = Path(os.environ['MAGNUM_UI_WHEEL'])
        self.assertEqual(hashlib.sha256(wheel.read_bytes()).hexdigest(), WHEEL_SHA)
        self.temporary = tempfile.TemporaryDirectory(prefix='magnum-create-regression-')
        self.addCleanup(self.temporary.cleanup)
        extracted = Path(self.temporary.name)
        with zipfile.ZipFile(wheel) as archive:
            archive.extractall(extracted)
        self.static = extracted / 'magnum_ui/static/dashboard/container-infra'
        subprocess.run([sys.executable, str(ROOT / 'enhance_magnum_ui.py')],
                       env={**os.environ, 'MAGNUM_UI_ROOT': str(self.static)},
                       check=True, capture_output=True, text=True)

    def run_case(self, scenario):
        result = subprocess.run(['node', str(ROOT / 'tests/run-workflow.js'),
            str(self.static / 'clusters/workflow/workflow.service.js'), scenario],
            capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_multiple_az_dependencies_initialize_hidden_selector(self): self.run_case('multiple')
    def test_single_az_defaults_are_preserved(self): self.run_case('one')
    def test_zero_az_does_not_manufacture_a_selection(self): self.run_case('zero')
    def test_missing_binding_is_an_executable_regression(self): self.run_case('missing-binding')
    def test_dependency_failure_is_not_converted_to_success(self): self.run_case('dependency-failure')


if __name__ == '__main__':
    unittest.main()
