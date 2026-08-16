#!/usr/bin/env bash
set -euo pipefail

operation=${1:?deploy or verify}
: "${DEVELOPMENT_NAMESPACE:?development wrapper must set DEVELOPMENT_NAMESPACE}"
: "${DEVELOPMENT_NAME:?development wrapper must set DEVELOPMENT_NAME}"
[[ $DEVELOPMENT_NAME == p0-core-orchestration ]]
[[ $DEVELOPMENT_NAMESPACE == development-p0-core-orchestration ]]
root=$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)
manifest="$root/automation/development/manifests/p0-core-orchestration.yaml"
host=p0-core-orchestration.dev.dcn.ssu.ac.kr

case "$operation" in
  deploy)
    : "${CORE_ORCHESTRATOR_IMAGE:?set an immutable development image reference}"
    [[ $CORE_ORCHESTRATOR_IMAGE =~ ^[^[:space:]]+@sha256:[0-9a-f]{64}$ ]] || {
      echo 'CORE_ORCHESTRATOR_IMAGE must be pinned by sha256 digest' >&2; exit 2;
    }
    if ! kubectl -n "$DEVELOPMENT_NAMESPACE" get secret p0-core-orchestration >/dev/null 2>&1; then
      kubectl -n "$DEVELOPMENT_NAMESPACE" create secret generic p0-core-orchestration \
        --from-literal=signing-key="$(openssl rand -hex 32)" \
        --from-literal=event-key="$(openssl rand -hex 32)"
    fi
    kubectl -n "$DEVELOPMENT_NAMESPACE" get secret p0-openstack-provider >/dev/null 2>&1 || {
      echo 'missing dedicated development provider Secret p0-openstack-provider' >&2; exit 2;
    }
    if ! kubectl -n "$DEVELOPMENT_NAMESPACE" get secret p0-core-backends >/dev/null 2>&1; then
      postgres_password=$(openssl rand -hex 32)
      rabbit_password=$(openssl rand -hex 32)
      database_url="postgresql://core:${postgres_password}@p0-core-postgresql:5432/core"
      rabbit_url="amqp://dcn_p0_track_a_dev:${rabbit_password}@rabbitmq.openstack.svc.cluster.local:5672/%2Fdcn-p0-track-a-development"
      kubectl -n "$DEVELOPMENT_NAMESPACE" create secret generic p0-core-backends \
        --from-literal=postgres-password="$postgres_password" \
        --from-literal=database-url="$database_url" \
        --from-literal=rabbitmq-password="$rabbit_password" \
        --from-literal=rabbitmq-url="$rabbit_url" >/dev/null
      unset postgres_password rabbit_password database_url rabbit_url
    fi
    rabbit_pod=$(kubectl -n openstack get pod -l application=rabbitmq -o jsonpath='{.items[0].metadata.name}')
    [[ -n $rabbit_pod ]] || { echo 'RabbitMQ pod was not found' >&2; exit 2; }
    rabbit_password=$(kubectl -n "$DEVELOPMENT_NAMESPACE" get secret p0-core-backends -o go-template='{{index .data "rabbitmq-password" | base64decode}}')
    kubectl -n openstack exec "$rabbit_pod" -c rabbitmq -- rabbitmqctl add_vhost /dcn-p0-track-a-development >/dev/null 2>&1 || true
    if kubectl -n openstack exec "$rabbit_pod" -c rabbitmq -- rabbitmqctl list_users --silent | awk '{print $1}' | grep -qx dcn_p0_track_a_dev; then
      kubectl -n openstack exec "$rabbit_pod" -c rabbitmq -- rabbitmqctl change_password dcn_p0_track_a_dev "$rabbit_password" >/dev/null
    else
      kubectl -n openstack exec "$rabbit_pod" -c rabbitmq -- rabbitmqctl add_user dcn_p0_track_a_dev "$rabbit_password" >/dev/null
    fi
    unset rabbit_password
    kubectl -n openstack exec "$rabbit_pod" -c rabbitmq -- rabbitmqctl set_permissions \
      -p /dcn-p0-track-a-development dcn_p0_track_a_dev '^dcn\.track-a\.' '^dcn\.track-a\.' '^dcn\.track-a\.' >/dev/null
    sed -e "s|__NAMESPACE__|$DEVELOPMENT_NAMESPACE|g" \
        -e "s|__IMAGE__|$CORE_ORCHESTRATOR_IMAGE|g" "$manifest" | kubectl apply -f -
    ;;
  verify)
    kubectl -n "$DEVELOPMENT_NAMESPACE" rollout status deployment/p0-core-orchestration --timeout=5m
    kubectl -n "$DEVELOPMENT_NAMESPACE" rollout status statefulset/p0-core-postgresql --timeout=5m
    image=$(kubectl -n "$DEVELOPMENT_NAMESPACE" get deploy p0-core-orchestration -o jsonpath='{.spec.template.spec.containers[0].image}')
    [[ $image =~ @sha256:[0-9a-f]{64}$ ]]
    worker_image=$(kubectl -n "$DEVELOPMENT_NAMESPACE" get deploy p0-core-orchestration -o jsonpath='{.spec.template.spec.containers[1].image}')
    [[ $worker_image == "$image" ]]
    scheduler_image=$(kubectl -n "$DEVELOPMENT_NAMESPACE" get deploy p0-core-orchestration -o jsonpath='{.spec.template.spec.containers[2].image}')
    [[ $scheduler_image == "$image" ]]
    outbox_image=$(kubectl -n "$DEVELOPMENT_NAMESPACE" get deploy p0-core-orchestration -o jsonpath='{.spec.template.spec.containers[3].image}')
    [[ $outbox_image == "$image" ]]
    node=$(kubectl -n "$DEVELOPMENT_NAMESPACE" get pod -l app.kubernetes.io/name=p0-core-orchestration -o jsonpath='{.items[0].spec.nodeName}')
    [[ $node == "${DEVELOPMENT_NODE:?}" ]]
    curl --fail --silent --show-error --insecure --connect-timeout 5 --max-time 15 \
      --resolve "$host:443:${DEVELOPMENT_GATEWAY_IP:?}" "https://$host/healthz" | grep -q '"status": "ok"'
    pod=$(kubectl -n "$DEVELOPMENT_NAMESPACE" get pod -l app.kubernetes.io/name=p0-core-orchestration -o jsonpath='{.items[0].metadata.name}')
    kubectl -n "$DEVELOPMENT_NAMESPACE" exec "$pod" -c worker -- python -m core.provider_probe | grep -qx OPENSTACK_PROVIDER_READ_ONLY_PROBE_OK
    ;;
  rollback)
    kubectl -n "$DEVELOPMENT_NAMESPACE" scale deployment/p0-core-orchestration --replicas=0
    ;;
  *) echo "unsupported operation: $operation" >&2; exit 2 ;;
esac
