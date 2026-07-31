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
9. Enable both `ovn` and `amphora`, keeping OVN as the default provider, and
   deploy two workers plus two health managers as node-bound DaemonSets.
10. Create the Amphora management network, fixed node ports, security group,
    flavor, keypair, image tag, and dual intermediate CA hierarchy with the
    idempotent reconciliation script.
11. Copy only the internal Gateway `ca.crt` into the OpenStack namespace,
    mount it in Octavia, and configure `[service_auth] cafile` in addition to
    the Glance, Nova, and Cinder CA options.
12. Initialize management interfaces from the fixed Neutron port address and
    skip DHCP when that address is present.
13. Use an explicit headless-service RabbitMQ transport URL and a URL-safe,
    independently rotated Octavia credential. Keep all credentials and
    private keys only in SOPS-encrypted files.
14. Build the digest-pinned worker image in `images/octavia-ovn` with the
    2026.1-constrained Redis Python client.
15. Deploy the frozen `prerequisites/octavia-jobboard` Valkey chart with three
    Ceph-backed data nodes and Sentinel sidecars, then enable the Redis
    Taskflow jobboard and MariaDB persistence.
16. Keep Valkey data authentication enabled. Leave Sentinel discovery
    unauthenticated because Octavia 2026.1/Taskflow does not pass the data
    credential to Sentinel.
17. Patch both Octavia DaemonSets to render image pull Secrets. The upstream
    DaemonSet templates omitted the helper used by the Deployment templates,
    which caused private worker images to fail on nodes without a cached copy.
