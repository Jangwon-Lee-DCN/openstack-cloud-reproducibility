FROM quay.io/airshipit/nova@sha256:92d38954146b2dc5be5a35faf5474f7f103894c7669462d1cb81defab4782e29

COPY nova-*.tar.gz /tmp/nova-source.tar.gz
# The Airship runtime venv intentionally omits pip but retains Python's
# checksum-pinned ensurepip payload. Bootstrap pip only for this layer, replace
# Nova from the exact sdist, then remove pip again to preserve the runtime-only
# base-image contract.
RUN python3 -m ensurepip --upgrade \
    && python3 -m pip install --no-cache-dir --no-deps /tmp/nova-source.tar.gz \
    && rm -f /tmp/nova-source.tar.gz \
    && python3 -m pip uninstall --yes pip
