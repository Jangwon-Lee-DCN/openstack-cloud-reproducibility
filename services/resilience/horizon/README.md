# Independent Horizon Track C panel

This package owns only the Track C dashboard and panel registration. It does
not edit Horizon's common navigation, image, settings, container or deployment
files. Integration must install the package, copy the `enabled` file and route
`/resilience-api/` through a Keystone-authenticating reverse proxy that removes
all inbound identity headers before setting `X-Verified-Project-ID`.

The development panel is inventory-only. Create, update, delete, reconcile and
live failover buttons stay absent until Keystone, OPA and real Track A/B
clients pass cross-project acceptance.
