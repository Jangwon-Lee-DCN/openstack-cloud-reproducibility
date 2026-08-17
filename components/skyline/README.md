# skyline operational contract

This is the authoritative issue, remediation, reconciliation, and verification contract for `skyline`.

## Known issues and scope

## HA scheduling gap

The upstream OpenStack-Helm `2026.1.0` Skyline deployment declares replica and
toleration values but does not render pod anti-affinity or control-plane
tolerations. In this two-controller PoC, two replicas can therefore remain on
the untainted controller instead of tolerating and spreading to both nodes.

## Horizon fallback under a path prefix

Skyline owns the cloud root URL. Horizon remains a compatibility fallback at
`/horizon/`. Horizon must generate prefixed URLs while Gateway API removes the
prefix before forwarding to Apache. The upstream `/` health probes follow the
prefixed login redirect and receive a 404 from the unprefixed backend.

## DB migration password constraint

Skyline APIServer 8.0.0 passes its SQLAlchemy URL through Python
`configparser`. A randomly generated password containing URL-escaped percent
sequences such as `%2F` causes Alembic to fail with `invalid interpolation
syntax`. Skyline DB passwords must use the documented URL-safe hex profile.

## Remediation

1. Patch `skyline/templates/deployment.yaml` to render the standard
   helm-toolkit pod anti-affinity and toleration snippets.
2. Configure two Skyline replicas, required hostname anti-affinity, and a
   `minAvailable: 1` PodDisruptionBudget.
3. Generate the Skyline database password with `openssl rand -hex 32`; keep it
   and all other credentials only in SOPS-encrypted values.
4. Patch Horizon readiness and liveness probes to `/auth/login/`, the direct
   backend health endpoint that does not follow the externally prefixed login
   redirect.
5. Set Horizon `WEBROOT`, login/logout/static URLs, and `FORCE_SCRIPT_NAME` for
   `/horizon/`.
6. Route `/` to `skyline-api:9999` and `/horizon` to `horizon-int:80`, with the
   Horizon prefix removed by Gateway API.

The clean upstream packages remain under `helm/packages/upstream/`. Runtime
reconciliation uses `helm/packages/patched/skyline-2026.1.0.tgz` and
`helm/packages/patched/horizon-2026.1.0.tgz`, both locked by SHA-256.

## Reconciliation

Skyline is installed after Horizon and before the public HTTPRoute is applied.
The release is fully represented by `release-lock.yaml` and the encrypted
`deploy/releases/skyline.values.sops.yaml` snapshot.

```bash
./deploy/scripts/reconcile-full-stack.sh
```

The expected public dashboard policy is:

- `https://cloud.dcn.ssu.ac.kr/`: Skyline user dashboard
- `https://cloud.dcn.ssu.ac.kr/horizon/`: Horizon administrator and
  compatibility fallback

If an interrupted first install created the `skyline` MariaDB user with a
different password, align that account with the encrypted URL-safe password
before retrying the hooks. Do not print the password or place it in shell
history. This is only a failed-initial-install recovery; an ordinary clean
reconciliation requires no manual database mutation.

## Verification

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
