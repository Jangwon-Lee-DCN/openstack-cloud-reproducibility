from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_rack_secondaries_force_forward_and_reverse_zone_retransfer_before_verification():
    tasks = (
        ROOT / "automation/ansible/roles/bind_dns/tasks/rack.yml"
    ).read_text()

    retransfer = tasks.index(
        "Force secondary rack-aware zones to retransfer after primary reconciliation"
    )
    verification = tasks.index("Verify every inventory hostname locally")

    assert retransfer < verification
    assert "rndc retransfer {{ item }}" in tasks
    assert "[dns_domain] + (dns_reverse_zones | map(attribute='zone') | list)" in tasks
    assert "dns_role == 'secondary'" in tasks
    assert "not ansible_check_mode" in tasks
