#!/usr/bin/env bash
set -euo pipefail

if test "$#" -ne 2; then
  echo "usage: $0 <CAPI-cluster-name> <lb|no-lb>" >&2
  exit 2
fi

cluster_name="$1"
endpoint_mode="$2"
namespace="$(
  kubectl get cluster.cluster.x-k8s.io --all-namespaces \
    -o jsonpath="{range .items[?(@.metadata.name=='${cluster_name}')]}{.metadata.namespace}{end}"
)"

test -n "${namespace}"
case "${endpoint_mode}" in
  lb|no-lb) ;;
  *) echo "endpoint mode must be lb or no-lb" >&2; exit 2 ;;
esac

kubeconfig="$(mktemp)"
cleanup() {
  rm -f -- "${kubeconfig}"
}
trap cleanup EXIT

kubectl -n "${namespace}" get secret "${cluster_name}-kubeconfig" \
  -o jsonpath='{.data.value}' | base64 -d >"${kubeconfig}"
chmod 0600 "${kubeconfig}"

api_endpoint="$(
  kubectl -n "${namespace}" get openstackcluster "${cluster_name}" \
    -o jsonpath='{.spec.controlPlaneEndpoint.host}:{.spec.controlPlaneEndpoint.port}'
)"
api_host="${api_endpoint%:*}"
api_port="${api_endpoint##*:}"
lb_enabled="$(
  kubectl -n "${namespace}" get openstackcluster "${cluster_name}" \
    -o jsonpath='{.spec.apiServerLoadBalancer.enabled}'
)"

if test "${endpoint_mode}" = lb; then
  test "${lb_enabled}" = true
else
  test "${lb_enabled:-false}" != true
fi
timeout 5 bash -c '</dev/tcp/$1/$2' _ "${api_host}" "${api_port}"

test "$(kubectl --kubeconfig "${kubeconfig}" get nodes --no-headers | wc -l)" -eq 2
test "$(
  kubectl --kubeconfig "${kubeconfig}" get nodes \
    -o jsonpath='{range .items[*]}{.status.conditions[?(@.type=="Ready")].status}{"\n"}{end}' |
    grep -c '^True$'
)" -eq 2
test "$(
  kubectl --kubeconfig "${kubeconfig}" get nodes \
    -l node-role.kubernetes.io/control-plane --no-headers | wc -l
)" -eq 1

non_control_plane_nodes="$(
  kubectl --kubeconfig "${kubeconfig}" get nodes -o json |
    jq '[.items[] | select(.metadata.labels["node-role.kubernetes.io/control-plane"] == null)] | length'
)"
test "${non_control_plane_nodes}" -eq 1

not_deployed="$(
  kubectl -n "${namespace}" get helmreleases.addons.stackhpc.com \
    -o json |
    jq --arg prefix "${cluster_name}-" \
      '[.items[] | select(.metadata.name | startswith($prefix)) |
        select(.status.phase != "Deployed")] | length'
)"
test "${not_deployed}" -eq 0

kubectl --kubeconfig "${kubeconfig}" create namespace platform-verification \
  --dry-run=client -o yaml | kubectl --kubeconfig "${kubeconfig}" apply -f -
kubectl --kubeconfig "${kubeconfig}" -n platform-verification apply -f - <<'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web
spec:
  replicas: 1
  selector:
    matchLabels: {app: web}
  template:
    metadata:
      labels: {app: web}
    spec:
      containers:
        - name: web
          image: docker.io/library/nginx:1.29.0-alpine
          resources:
            requests: {cpu: 10m, memory: 16Mi}
            limits: {memory: 64Mi}
---
apiVersion: v1
kind: Service
metadata:
  name: web
spec:
  selector: {app: web}
  ports:
    - {port: 80, targetPort: 80}
EOF
kubectl --kubeconfig "${kubeconfig}" -n platform-verification rollout status \
  deployment/web --timeout=5m
kubectl --kubeconfig "${kubeconfig}" -n platform-verification delete pod network-check \
  --ignore-not-found --wait=true
kubectl --kubeconfig "${kubeconfig}" -n platform-verification run network-check \
  --image=docker.io/curlimages/curl:8.14.1 \
  --restart=Never --command -- \
  sh -ec 'nslookup kubernetes.default.svc.cluster.local; curl -fsS http://web.platform-verification.svc.cluster.local; curl -fsSI https://www.example.com'
kubectl --kubeconfig "${kubeconfig}" -n platform-verification wait \
  --for=jsonpath='{.status.phase}'=Succeeded pod/network-check --timeout=5m

echo "${cluster_name}: ${endpoint_mode}, 1 control plane, 1 worker, add-ons, DNS, service networking, and internet egress verified"
