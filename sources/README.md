# Upstream source pins

This directory preserves source archives needed to rebuild locally modified
controller images when upstream Git hosting is unavailable.

Verify and apply the CAPO patch:

```bash
cd sources
sha256sum --check SHA256SUMS
tar -xzf upstream/cluster-api-provider-openstack-v0.14.6.tar.gz
cd cluster-api-provider-openstack-0.14.6
patch -p1 < ../patches/capo/port-list-limit.patch
```

The archive is the unmodified GitHub `v0.14.6` tag. Local changes remain in a
separate patch so Git history and review show the exact deviation.
