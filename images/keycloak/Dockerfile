FROM quay.io/keycloak/keycloak:26.7.0

# The Keycloak Operator starts managed servers with `start --optimized`.
# Persist every build-time option needed by this deployment in the image.
ENV KC_DB=mariadb
ENV KC_HEALTH_ENABLED=true
ENV KC_METRICS_ENABLED=true

RUN /opt/keycloak/bin/kc.sh build

