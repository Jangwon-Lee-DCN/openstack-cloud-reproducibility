FROM quay.io/keycloak/keycloak:26.7.0@sha256:0f198be292568439d700cdbfb893e69a6009bb43a94a06a945b1d3d506c76b13

# The Keycloak Operator starts managed servers with `start --optimized`.
# Persist every build-time option needed by this deployment in the image.
ENV KC_DB=mariadb
ENV KC_HEALTH_ENABLED=true
ENV KC_METRICS_ENABLED=true

COPY --chown=keycloak:keycloak themes/dcn-openstack /opt/keycloak/themes/dcn-openstack

RUN /opt/keycloak/bin/kc.sh build
