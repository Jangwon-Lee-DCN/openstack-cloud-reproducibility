# Internal Endpoint Contract

| Service | Internal URL |
|---|---|
| Identity | `https://api.internal.cloud.dcn.ssu.ac.kr/identity/v3` |
| Compute | `https://api.internal.cloud.dcn.ssu.ac.kr/compute/v2.1` |
| Network | `https://api.internal.cloud.dcn.ssu.ac.kr/network` |
| Image | `https://api.internal.cloud.dcn.ssu.ac.kr/image` |
| Volume v3 | `https://api.internal.cloud.dcn.ssu.ac.kr/volume/v3` |
| Orchestration | `https://api.internal.cloud.dcn.ssu.ac.kr/orchestration/v1/%(tenant_id)s` |
| Load Balancer | `https://api.internal.cloud.dcn.ssu.ac.kr/load-balancer` |
| Key Manager | `https://api.internal.cloud.dcn.ssu.ac.kr/key-manager` |
| Container Infrastructure | `https://api.internal.cloud.dcn.ssu.ac.kr/container-infra/v1` |

The Gateway also routes the Keystone-native `/v3` path. This compatibility
alias is required by generic `keystoneauth` discovery: some clients normalize
the catalog URL `/identity/v3` to origin-root `/v3` while re-scoping an
existing project token. `/identity/v3` remains the canonical catalog URL.
The Gateway similarly routes Nova's native `/v2.1` version-discovery path;
ordinary compute operations continue to use the canonical `/compute/v2.1`.

CAPO and the Magnum CAPI driver use the `internal` interface. Workload
OpenStack CCM and Cinder CSI credentials also use these URLs and trust the
internal Gateway CA.
