# FIX: Octavia OVN Provider Integration

1. Build the image in `images/octavia-ovn` with the 2026.1 OVN provider and its
   constrained dependencies, then deploy the recorded Harbor digest.
2. Discover every NB and SB EndpointSlice address and configure comma-separated
   OVSDB remotes.
3. Patch the driver-agent chart volume from `emptyDir` to the node-local
   `/var/lib/octavia/run` hostPath. Mount the same path in Octavia API at
   `/var/run/octavia`.
4. Create that directory on both controllers with owner `42424:42424` and mode
   `0750`.
5. Use required hostname anti-affinity and two replicas for API, driver-agent,
   and housekeeping.
6. Set `[neutron] valid_interfaces = internal`.
7. Install the 2026.1 Octavia Horizon plugin in the frozen custom Horizon
   image and map Skyline's `load-balancer` service to `octavia`.
8. Use config-drive test backends and permit the intended client CIDRs on
   backend TCP/80.
