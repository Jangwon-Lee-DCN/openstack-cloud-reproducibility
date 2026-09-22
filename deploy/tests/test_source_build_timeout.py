#!/usr/bin/env python3
"""Ensure slow source builds cannot outlive their serialized queue request."""

from pathlib import Path


root = Path(__file__).resolve().parents[2]
source = (root / "deploy/scripts/build-images.sh").read_text()

assert "SOURCE_BUILD_TIMEOUT_SECONDS=${SOURCE_BUILD_TIMEOUT_SECONDS:-7200}" in source
assert "activeDeadlineSeconds: $((SOURCE_BUILD_TIMEOUT_SECONDS + 300))" in source
assert "deadline=$((SECONDS + SOURCE_BUILD_TIMEOUT_SECONDS))" in source
assert 'kubectl delete job "$job"' in source
assert 'dcn.ssu.ac.kr/image-build-job=$job' in source
assert 'timed out after ${SOURCE_BUILD_TIMEOUT_SECONDS}s' in source
