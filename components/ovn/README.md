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
