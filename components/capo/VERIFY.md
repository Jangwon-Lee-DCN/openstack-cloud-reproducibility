# VERIFY

Verify that:

1. both CAPO replicas are Ready on different controller nodes;
2. their image ID equals the pinned digest;
3. an OpenStackCluster can resolve the selected external network;
4. one control-plane and one worker Nova server become ACTIVE;
5. CAPO and CCM both report provider IDs in `openstack:///UUID` form.
