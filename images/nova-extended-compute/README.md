# Nova extended compute image

This image layers the exact `nova-extended-compute` Git revision over the
immutable Airship Nova 2026.1 base. The image definition owns only packaging;
all downstream Nova behavior and tests belong to the source repository.

Submit it through `dcn-image-build` with both `reproducibility` and
`nova_extended_compute` revisions. Direct builds and uncommitted sources are
rejected by the queue contract.
