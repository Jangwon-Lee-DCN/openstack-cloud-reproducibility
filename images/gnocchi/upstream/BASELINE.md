# Gnocchi Image Baseline

The OpenStack-Helm 2026.1.0 chart declares Gnocchi application version 3.0.3
and legacy image defaults. The replacement image is based on
`python:3.12-slim-bookworm` and installs the published `gnocchi` Python
package. The exact replacement is added in a separate fix commit.
