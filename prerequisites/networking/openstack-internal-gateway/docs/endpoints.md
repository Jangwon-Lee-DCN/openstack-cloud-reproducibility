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

CAPO and the Magnum CAPI driver use the `internal` interface. Workload
OpenStack CCM and Cinder CSI credentials also use these URLs and trust the
internal Gateway CA.
