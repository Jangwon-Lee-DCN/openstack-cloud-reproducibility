# ISSUE

The upstream OpenStack-Helm 2026.1.0 Magnum chart and Airship Noble image
cannot directly run the selected CAPI Helm driver:

- the image has only the legacy Heat driver and no Helm client;
- the CAPI driver expects a static kubeconfig token;
- the Airship image lacks the chart's `magnum-api-wsgi` path;
- the chart's filter-style healthcheck is incompatible with the image's
  `oslo.middleware`;
- private-registry pulls, control-plane taints, and two-node HA require
  additional chart settings.
