# ovn operational contract

This is the authoritative issue, remediation, reconciliation, and verification contract for `ovn`.

## Known issues and scope

The OVN 2026.1.0 templates did not render the site tolerations needed by OVN
controller, northd, and OVSDB Pods on tainted control-plane nodes. OVSDB NB/SB
also mounted the shared host `/run/openvswitch`, causing socket and filesystem
coupling between otherwise independent database Pods.

## Remediation

The chart explicitly renders component tolerations for controller, northd,
OVSDB NB, and OVSDB SB. The two database StatefulSets use pod-local `emptyDir`
for `/run/openvswitch` while their actual databases remain on configured
persistent storage. The patched package is stored at
`helm/packages/patched/ovn-2026.1.0.tgz`.

## Optional service bridges — development candidate

`conf.ovn_node_extra_bridges` defaults to an empty map. Explicit node entries
contain `physnet`, `bridge`, `interface`, `parent`, and `vlan`. Site allocation
and node selection belong to the production inventory, not this chart.
The host network reconciler creates the addressless VLAN interface; OVN init
owns its OVS bridge and appends the mapping to the existing rack mapping.
Do not create the same bridge through Netplan or overwrite the whole mapping
with a one-time command.

Initialization rejects wrong VLAN parents/IDs, addressed interfaces, foreign
port bindings, unowned bridges, and unexpected bridge ports before mutation.
OVN-created localnet patch ports are retained only when their localnet markers
match and their reciprocal patch peer belongs to `br-int`. This matters on
restart after OVN has connected the first VM: a bridge is no longer empty.
The helper does not remove old bridges or retire clients when a value is
removed. Retirement requires an explicit fenced lifecycle and rollback plan.

`python3 -m unittest discover -s deploy/tests -p test_ovn_extra_bridges.py -v`
checks actual chart rendering and executes the rendered shell with command
stubs, including repeat initialization and invalid patch pairs. These checks
are not real OVS dataplane, CPU VM NFS, or restart acceptance. The candidate is
packaged with its checksum in `release-lock.yaml`; it is not promoted and
production defaults remain unchanged. Isolated real OVS acceptance,
packaged-source equivalence, full VM isolation acceptance,
and the production reconciler/approval gates remain mandatory.

`OVS_TEST_ROOT=/path/to/extracted/packages python3 -m unittest discover -s
deploy/tests -p test_ovn_extra_bridges_ovsdb.py -v` additionally runs a real
private OVSDB server and `ovs-vsctl`, without installing a host service. The
root must contain `usr/bin/ovs-vsctl`, `usr/bin/ovsdb-tool`,
`usr/sbin/ovsdb-server`, `usr/share/openvswitch/vswitch.ovsschema`, and required
shared libraries. It tests first/repeat initialization, reciprocal localnet
patch ports, mismatched-marker rejection, and unchanged external bridge.
Its database/socket are temporary and explicitly selected; `--no-wait` avoids
requiring a running switch daemon. IP commands remain simulated, so this is
database acceptance only, not Linux-interface, packet or CPU VM acceptance.

The production repository's `ai-space-ovn-bridge` development component runs
`deploy/tests/ovn_extra_bridges_kernel_fixture.py` on the designated utility
host in a private Linux network namespace. It uses actual OVSDB, ovs-vswitchd,
dummy parent and VLAN interfaces, and verifies unchanged host networking.
This covers kernel interface creation and repeated initializer execution;
it does not run ovn-controller, attach a physical switch or exercise an NFS VM.
The component uses extracted tools, not a host OVS service installation.
