ARG HORIZON_BASE
FROM ${HORIZON_BASE}

USER root

# Official OpenStack 2026.1 Horizon plugin and its two clients. Dependencies
# shared with Horizon already exist in the Airship image; use the released
# wheels directly and verify each immutable input before extraction.
ADD https://tarballs.openstack.org/magnum-ui/magnum_ui-18.0.0-py3-none-any.whl /tmp/magnum_ui.whl
ADD https://tarballs.openstack.org/python-magnumclient/python_magnumclient-4.10.0-py3-none-any.whl /tmp/python_magnumclient.whl
ADD https://tarballs.openstack.org/python-heatclient/python_heatclient-5.1.0-py3-none-any.whl /tmp/python_heatclient.whl

RUN echo "93139ab8e6401a7069fa22b0f39deecc9defd73eed62f0441b0923926914f72a  /tmp/magnum_ui.whl" | sha256sum -c - \
    && echo "4d2717f0e98202dfc8ef8f966186dec39ef221e1e4e666a4dc08a17445acb039  /tmp/python_magnumclient.whl" | sha256sum -c - \
    && echo "7c9b29265cdc9256d60ed9974d38469b76a99976e1ca50263faad11e6942433d  /tmp/python_heatclient.whl" | sha256sum -c - \
    && python3 -m zipfile -e /tmp/python_magnumclient.whl /var/lib/openstack/lib/python3.12/site-packages \
    && python3 -m zipfile -e /tmp/python_heatclient.whl /var/lib/openstack/lib/python3.12/site-packages \
    && python3 -m zipfile -e /tmp/magnum_ui.whl /var/lib/openstack/lib/python3.12/site-packages \
    && cp /var/lib/openstack/lib/python3.12/site-packages/magnum_ui/enabled/_13*.py /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/local/enabled/ \
    && cp /var/lib/openstack/lib/python3.12/site-packages/magnum_ui/enabled/_23*.py /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/local/enabled/ \
    && sed -i 's/\$gray-lighter/#eeeeee/g' /var/lib/openstack/lib/python3.12/site-packages/magnum_ui/static/dashboard/container-infra/clusters/clusters.scss \
    && python3 -c "import magnum_ui, magnumclient, heatclient" \
    && rm -f /tmp/*.whl
