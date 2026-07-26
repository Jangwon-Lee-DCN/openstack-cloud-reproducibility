# Skyline Issues

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
