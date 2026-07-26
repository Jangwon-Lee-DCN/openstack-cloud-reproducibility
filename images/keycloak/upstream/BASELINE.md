# Keycloak Image Baseline

- Upstream image: `quay.io/keycloak/keycloak:26.7.0`
- Upstream operator: Keycloak Operator `26.7.0`
- Source tag commit: `38fd7a0c84e15d4b66b37d1c2ea728ca2f5416a4`

The upstream runtime image is extended only to run the mandatory Quarkus
build for the MariaDB provider, health endpoint, and metrics endpoint. The
Operator invokes `start --optimized`, which intentionally skips this build at
runtime.

