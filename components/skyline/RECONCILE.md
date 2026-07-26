# Skyline Reconciliation

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
