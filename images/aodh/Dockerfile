FROM python:3.12-slim-bookworm

ARG AODH_VERSION=22.0.0

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential ca-certificates apache2 apache2-dev libapache2-mod-wsgi-py3 \
 && pip install --no-cache-dir \
      "aodh[mysql]==${AODH_VERSION}" \
      pymysql \
      pymemcache \
      python-memcached \
      mod_wsgi \
      uwsgi \
 && cp /usr/local/lib/python3.12/site-packages/mod_wsgi/server/mod_wsgi-py312*.so /usr/lib/apache2/modules/mod_wsgi.so \
 && apt-get purge -y --auto-remove build-essential apache2-dev \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --uid 42402 --create-home --shell /usr/sbin/nologin aodh \
 && install -d -o aodh -g aodh /etc/aodh /var/lib/aodh /var/lock/aodh

USER 42402:42402
EXPOSE 8042
ENTRYPOINT []
CMD ["aodh-api", "--config-file", "/etc/aodh/aodh.conf"]
