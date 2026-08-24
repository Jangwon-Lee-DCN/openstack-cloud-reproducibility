FROM quay.io/airshipit/nova:2026.1-ubuntu_noble@sha256:b60aeb6c9f960958a52b2adab0d065e82c9d46ed89755290fbc1417dd0e95a0d

# The build context is an exact git archive of nova-extended-compute. Replace
# the packaged Nova source while retaining the base image's runtime dependencies
# and OpenStack-Helm entrypoints.
COPY nova /var/lib/openstack/lib/python3.12/site-packages/nova
COPY verify_installed.py /workspace/nova-extended-compute/verify_installed.py
RUN /var/lib/openstack/bin/python -m compileall -q \
      /var/lib/openstack/lib/python3.12/site-packages/nova \
 && /var/lib/openstack/bin/python \
      /workspace/nova-extended-compute/verify_installed.py
