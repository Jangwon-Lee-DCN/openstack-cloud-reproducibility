# ISSUE: Nova Ceph Pool Replication on a Single-OSD PoC

Nova's storage initialization attempted to reduce a Ceph pool replication size
without the explicit confirmation required by Ceph. The Job failed in the
single-OSD PoC topology.
