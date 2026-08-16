# Governance worker image gate

No worker image is built in slice 0.1.0. Add it only with a tested worker source,
an immutable base image, SBOM, secret scan, destination-restricted NetworkPolicy,
and restart/checkpoint contract. The API image must not be reused as an implicit
credential worker.
