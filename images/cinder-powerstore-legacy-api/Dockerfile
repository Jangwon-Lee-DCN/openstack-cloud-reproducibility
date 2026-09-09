FROM quay.io/airshipit/cinder:2026.1-ubuntu_noble@sha256:2e4c071dc3bfe3df5ac7a75989e34006415f811be071a27c6cec38233d9e6014

COPY apply_compatibility.py /tmp/apply_compatibility.py
RUN /var/lib/openstack/bin/python /tmp/apply_compatibility.py \
    /var/lib/openstack/lib/python3.12/site-packages/cinder/volume/drivers/dell_emc/powerstore \
 && rm /tmp/apply_compatibility.py
