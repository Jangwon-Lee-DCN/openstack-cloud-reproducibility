FROM python:3.12-slim-bookworm

ARG GNOCCHI_VERSION=4.7.0

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential ca-certificates \
 && pip install --no-cache-dir \
      "gnocchi[mysql,s3,keystone]==${GNOCCHI_VERSION}" \
      pymemcache \
      python-memcached \
      uwsgi \
 && apt-get purge -y --auto-remove build-essential \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --uid 10001 --create-home --shell /usr/sbin/nologin gnocchi \
 && install -d -o gnocchi -g gnocchi /etc/gnocchi /var/lib/gnocchi /var/lock/gnocchi

USER 10001:10001
EXPOSE 8041
ENTRYPOINT []
CMD ["gnocchi-api", "--config-file", "/etc/gnocchi/gnocchi.conf"]

