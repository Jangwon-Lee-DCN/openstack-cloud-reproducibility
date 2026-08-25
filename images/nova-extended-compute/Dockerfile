FROM quay.io/airshipit/nova:2026.1-ubuntu_noble@sha256:b60aeb6c9f960958a52b2adab0d065e82c9d46ed89755290fbc1417dd0e95a0d

# The build context is an exact archive of nova-extended-compute. Replace the
# packaged Nova implementation while retaining the base runtime and chart
# entrypoints.
COPY --chown=42424:42424 nova /var/lib/openstack/lib/python3.12/site-packages/nova
COPY --chown=42424:42424 verify_installed.py /tmp/nova-extended-compute-verify.py
USER 42424:42424
RUN /var/lib/openstack/bin/python -m compileall -q \
      /var/lib/openstack/lib/python3.12/site-packages/nova \
 && /var/lib/openstack/bin/python /tmp/nova-extended-compute-verify.py
