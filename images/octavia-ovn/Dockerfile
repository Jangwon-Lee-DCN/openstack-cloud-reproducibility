FROM quay.io/airshipit/octavia@sha256:f38440062afb29db0c8d805f024c3a18e127a119b05b249d26962bc4716d9332

USER root

# The upstream Airship Octavia image does not include the OVN provider or the
# optional redis-py dependency required by Taskflow's Redis/Sentinel jobboard.
# Install both from the 2026.1 upper constraints into the existing OpenStack
# virtual environment.
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3-pip ca-certificates \
    && python3 -m pip install --break-system-packages --no-cache-dir \
       --constraint=https://releases.openstack.org/constraints/upper/2026.1 \
       --target=/var/lib/openstack/lib/python3.12/site-packages \
       redis==7.2.0 \
       https://tarballs.openstack.org/ovn-octavia-provider/ovn_octavia_provider-10.0.0-py3-none-any.whl \
    && /var/lib/openstack/bin/python3 -c "import ovn_octavia_provider, redis; from redis.sentinel import Sentinel; print(redis.__version__)" \
    && apt-get purge -y python3-pip \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*
