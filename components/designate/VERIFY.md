# VERIFY: Designate

Run:

```bash
cd /home/ubuntu/openstack-cloud-services
./deployment/openstack-helm/scripts/verify-designate.sh
```

Acceptance requires:

1. two ready replicas for each core Designate service and PowerDNS;
2. successful zone and A-record creation through the OpenStack API;
3. both resources reaching `ACTIVE`;
4. `192.168.21.9` returning the created authoritative A record;
5. both BIND controllers resolving the delegated record to the same value.
6. an authenticated Horizon request to `/horizon/project/dnszones/` returning
   HTTP 200 while the Octavia and VPC Python plugins remain importable.

The accepted test record is:

```text
www.designate-poc.cloud.dcn.ssu.ac.kr. A 192.0.2.80
```
