# Aodh Image Baseline

The OpenStack-Helm 2026.1.0 chart declares Aodh application version 22.0.0,
but its default runtime image was unavailable or incompatible in the target
environment. The replacement image is based on `python:3.12-slim-bookworm`.
The exact replacement is added in a separate fix commit.
