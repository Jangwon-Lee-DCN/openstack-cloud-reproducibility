# capo operational contract

This is the authoritative issue, remediation, reconciliation, and verification contract for `capo`.

## Known issues and scope

CAPO `v0.14.6` asks Neutron for a single matching port with `Limit: 1`.
This Neutron deployment returns a pagination link when the result count equals
the limit. Gophercloud `v2.10.0` then fails while collecting all pages with:

`json: cannot unmarshal string into Go value of type map[string]interface {}`

The failure prevents CAPO from resolving an explicitly selected external
network.

## Remediation

The local CAPO controller changes the port lookup limit from `1` to `2`.
The unique one-port result then contains no pagination link and retains the
original uniqueness check.

Pinned image:

`registry.dcn.ssu.ac.kr/openstack/capo-controller@sha256:91bfcbad65adfacd832ec6935011eee76790ac71b27e9d333d125a7d519f4cf8`

The upstream source tag, source checksum, and exact patch are preserved beside
this record.

## Reconciliation

1. Verify the upstream source archive checksum.
2. Apply `port-list-limit.patch` to CAPO `v0.14.6`.
3. Build the controller using the pinned upstream Dockerfile and push it to
   Harbor.
4. Pin the resulting digest in the management-cluster kustomization.
5. Copy the existing Harbor pull secret into `capo-system`; never copy its
   plaintext value into Git.
6. Reconcile both CAPO replicas and retain required cross-node anti-affinity.

## Verification

Verify that:

1. both CAPO replicas are Ready on different controller nodes;
2. their image ID equals the pinned digest;
3. an OpenStackCluster can resolve the selected external network;
4. one control-plane and one worker Nova server become ACTIVE;
5. CAPO and CCM both report provider IDs in `openstack:///UUID` form.
