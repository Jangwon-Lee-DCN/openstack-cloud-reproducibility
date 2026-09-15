from pathlib import Path

import yaml


ROOT = Path(__file__).parents[2]


def test_gpu_acceptance_container_is_digest_locked_and_internal():
    lock = yaml.safe_load((ROOT / "deploy/locks/gpu-runtime-container.yaml").read_text())
    digest = "sha256:133c78a0575303be34164d0b90137a042172bdf60696af01a3c424ab402d86e2"
    assert lock["schema"] == "dcn.ssu.ac.kr/gpu-runtime-container/v1"
    assert lock["source"].endswith("@" + digest)
    assert lock["destination_tag"].endswith(":12.8.1-base-ubuntu24.04")
    assert lock["destination"] == "registry.dcn.ssu.ac.kr/openstack/nvidia-cuda@" + digest
    assert lock["platform"] == "linux/amd64"
    assert ":latest" not in str(lock)
