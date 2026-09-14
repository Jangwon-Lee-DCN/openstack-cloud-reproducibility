import pathlib
import unittest

import yaml


ROOT = pathlib.Path(__file__).parents[2]


class GPUVfioPassthroughTest(unittest.TestCase):
    def test_vfio_mode_blocks_nvidia_udev_module_loads(self):
        tasks = yaml.safe_load(
            (
                ROOT
                / "automation/ansible/roles/gpu_vfio_passthrough/tasks/main.yml"
            ).read_text()
        )
        task = next(
            item
            for item in tasks
            if item["name"] == "Bind only the approved GPU functions to vfio-pci"
        )
        content = task["ansible.builtin.copy"]["content"]

        self.assertIn("options vfio-pci ids=", content)
        for module in ("nvidia", "nvidia_modeset", "nvidia_drm", "nvidia_uvm"):
            self.assertIn(f"install {module} /bin/false", content)
        self.assertNotIn("softdep nvidia ", content)


if __name__ == "__main__":
    unittest.main()
