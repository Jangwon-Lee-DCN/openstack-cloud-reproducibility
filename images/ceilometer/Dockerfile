FROM quay.io/airshipit/ceilometer@sha256:dc8732f8a91eafef6645298aead0fbaa8a1f82f9327fa4057ce9c428a6e9d31a

USER root
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3-libvirt \
 && cp -a /usr/lib/python3/dist-packages/libvirt* /var/lib/openstack/lib/python3.12/site-packages/ \
 && rm -rf /var/lib/apt/lists/*
