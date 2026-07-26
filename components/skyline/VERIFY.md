# Skyline Verification

Run the full locked verification:

```bash
./deploy/scripts/verify-full-stack.sh
```

Acceptance criteria:

- Helm releases `skyline` and `horizon` are `deployed` at chart version
  `2026.1.0`.
- Both deployments have two Ready replicas.
- One replica of each dashboard runs on each controller.
- Skyline has a PDB with `minAvailable: 1`.
- `openstack-public-services` is Accepted and has resolved backends.
- `GET https://cloud.dcn.ssu.ac.kr/` returns the Skyline console.
- `GET https://cloud.dcn.ssu.ac.kr/horizon/` redirects to
  `/horizon/auth/login/` and returns the Horizon login page.
- Keystone contains the `skyline` service user and the Skyline API can use the
  internal service catalog.

The dashboards are stateless. Their persistent state is MariaDB, Keystone, and
the existing OpenStack services; killing either dashboard pod must not lose
cloud state.
