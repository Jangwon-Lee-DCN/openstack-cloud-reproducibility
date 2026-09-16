from pathlib import Path

import yaml


ROOT = Path(__file__).parents[2]


def test_gpu_acceptance_container_is_digest_locked_and_internal():
    lock = yaml.safe_load((ROOT / "deploy/locks/gpu-runtime-container.yaml").read_text())
    index_digest = "sha256:133c78a0575303be34164d0b90137a042172bdf60696af01a3c424ab402d86e2"
    platform_digest = "sha256:e711c99333fdfe8ae1e677b4972be6c5021f0128a1d31f775c7e58d88921b6a9"
    assert lock["schema"] == "dcn.ssu.ac.kr/gpu-runtime-container/v1"
    assert lock["source"].endswith("@" + index_digest)
    assert lock["source_platform_digest"] == platform_digest
    assert lock["destination_tag"].endswith(":12.8.1-base-ubuntu24.04")
    assert lock["destination"] == "registry.dcn.ssu.ac.kr/openstack/nvidia-cuda@" + platform_digest
    assert lock["platform"] == "linux/amd64"
    assert ":latest" not in str(lock)
