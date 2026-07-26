# FIX: OVN Tolerations and Pod-Local OVSDB Runtime Directory

The chart explicitly renders component tolerations for controller, northd,
OVSDB NB, and OVSDB SB. The two database StatefulSets use pod-local `emptyDir`
for `/run/openvswitch` while their actual databases remain on configured
persistent storage. The patched package is stored at
`helm/packages/patched/ovn-2026.1.0.tgz`.
