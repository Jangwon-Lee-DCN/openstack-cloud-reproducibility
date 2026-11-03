from pathlib import Path
import re
import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_horizon_candidate_is_immutable_and_allowed_with_exactly_one_rollback():
    values = yaml.safe_load((ROOT/'deploy/values/site/horizon.yaml').read_text())
    candidate = values['images']['tags']['horizon']
    assert re.fullmatch(r'[A-Za-z0-9./:_-]+@sha256:[a-f0-9]{64}', candidate)
    policy = next(yaml.safe_load_all((ROOT/'deploy/manifests/horizon-image-admission-lock.yaml').read_text()))
    assert policy['spec']['failurePolicy'] == 'Fail'
    expression = policy['spec']['validations'][0]['expression']
    allowed = re.findall(r"'([^']+@sha256:[a-f0-9]{64})'", expression)
    assert len(allowed) == 2 and len(set(allowed)) == 2
    assert candidate in allowed
    binding = list(yaml.safe_load_all((ROOT/'deploy/manifests/horizon-image-admission-lock.yaml').read_text()))[1]
    assert binding['spec']['validationActions'] == ['Deny']
