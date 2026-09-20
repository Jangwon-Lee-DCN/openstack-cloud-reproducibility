import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_helper_is_fail_closed_and_caps_requested_values():
    source = (ROOT / "files/dcn-storage-nic-ring").read_text()
    assert 'test -e "/sys/class/net/$interface/device"' in source
    assert "(( rx_target > max_rx )) && rx_target=$max_rx" in source
    assert "(( tx_target > max_tx )) && tx_target=$max_tx" in source
    assert 'test "$current_rx" = "$rx_target"' in source
    assert 'test "$current_tx" = "$tx_target"' in source


def test_service_waits_for_network_and_uses_explicit_environment():
    source = (ROOT / "files/dcn-storage-nic-ring.service").read_text()
    assert "After=network-online.target" in source
    assert "EnvironmentFile=/etc/default/dcn-storage-nic-ring" in source
    assert "${INTERFACE} ${RX_TARGET} ${TX_TARGET}" in source
