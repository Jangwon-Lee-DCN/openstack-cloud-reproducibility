# Patched Helm Packages

This directory is intentionally empty of chart archives today because the
telemetry corrections are implemented as values and external manifests; the
clean upstream chart sources remain byte-for-byte unchanged.

If a chart source patch becomes necessary, make it in a dedicated Git commit,
package the resulting chart here, update a `SHA256SUMS` file, and reference the
corresponding ISSUE/FIX documents.
