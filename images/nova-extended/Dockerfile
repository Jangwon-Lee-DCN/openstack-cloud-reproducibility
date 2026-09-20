FROM quay.io/airshipit/nova@sha256:92d38954146b2dc5be5a35faf5474f7f103894c7669462d1cb81defab4782e29

COPY nova-*.tar.gz /tmp/nova-source.tar.gz
RUN python3 -m pip install --no-cache-dir --no-deps /tmp/nova-source.tar.gz \
    && rm -f /tmp/nova-source.tar.gz
