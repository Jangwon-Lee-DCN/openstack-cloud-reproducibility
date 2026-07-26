# ISSUE: OVN Control-Plane Scheduling and OVSDB Socket Collision

The OVN 2026.1.0 templates did not render the site tolerations needed by OVN
controller, northd, and OVSDB Pods on tainted control-plane nodes. OVSDB NB/SB
also mounted the shared host `/run/openvswitch`, causing socket and filesystem
coupling between otherwise independent database Pods.
