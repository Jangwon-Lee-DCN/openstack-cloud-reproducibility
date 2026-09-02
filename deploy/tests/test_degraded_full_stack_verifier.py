from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_unready_pod_exception_is_exact_and_fail_closed():
    verifier = (ROOT / "deploy/scripts/verify-full-stack.sh").read_text()
    assert 'ALLOWED_UNREADY_PODS="${ALLOWED_UNREADY_PODS:-}"' in verifier
    assert 'name in allowed' in verifier
    assert 'missing = allowed - seen_allowed' in verifier
    assert 'allowed unready Pods were not observed unready' in verifier
