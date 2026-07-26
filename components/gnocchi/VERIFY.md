# VERIFY: Gnocchi

- Two API and two metricd Pods are Ready and split across controllers.
- Both PodDisruptionBudgets allow one controlled disruption.
- `/metric/healthcheck` returns HTTP 200 through the public Gateway.
- The OBC is Bound and its RGW user permits at least ten buckets.
- A real Ceilometer measure creates rows in the Gnocchi metric and resource
  indexes and is retrievable through the authenticated API.

The last condition is currently pending in the PoC and is a release gate.
