#!/usr/bin/env bash
set -euo pipefail

namespace=${CONNECTIVITY_NAMESPACE:-rebuild-connectivity-test}
image=${CONNECTIVITY_IMAGE:-busybox:1.36.1}

# Make remote/root execution deterministic instead of relying on the invoking
# user's optional ~/.kube/config. Callers can still select another cluster by
# exporting KUBECONFIG explicitly.
if [[ -z ${KUBECONFIG:-} && -r /etc/kubernetes/admin.conf ]]; then
  export KUBECONFIG=/etc/kubernetes/admin.conf
fi

cleanup() {
  kubectl delete namespace "$namespace" --ignore-not-found --wait=true >/dev/null
}
trap cleanup EXIT

cleanup
kubectl create namespace "$namespace" >/dev/null

kubectl apply -n "$namespace" -f - <<EOF >/dev/null
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: connectivity-server
spec:
  selector:
    matchLabels:
      app: connectivity-server
  template:
    metadata:
      labels:
        app: connectivity-server
    spec:
      tolerations:
        - operator: Exists
      containers:
        - name: server
          image: ${image}
          command: ["/bin/sh", "-c"]
          args:
            - mkdir -p /www && echo ok >/www/index.html && exec httpd -f -p 8080 -h /www
          ports:
            - name: http
              containerPort: 8080
---
apiVersion: v1
kind: Service
metadata:
  name: connectivity-server
spec:
  selector:
    app: connectivity-server
  ports:
    - name: http
      port: 8080
      targetPort: http
---
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: connectivity-client
spec:
  selector:
    matchLabels:
      app: connectivity-client
  template:
    metadata:
      labels:
        app: connectivity-client
    spec:
      tolerations:
        - operator: Exists
      containers:
        - name: client
          image: ${image}
          command: ["/bin/sh", "-c", "exec sleep 3600"]
EOF

kubectl rollout status -n "$namespace" daemonset/connectivity-server --timeout=5m
kubectl rollout status -n "$namespace" daemonset/connectivity-client --timeout=5m

mapfile -t server_ips < <(
  kubectl get pods -n "$namespace" -l app=connectivity-server \
    -o jsonpath='{range .items[*]}{.status.podIP}{"\n"}{end}'
)
mapfile -t clients < <(
  kubectl get pods -n "$namespace" -l app=connectivity-client \
    -o name
)

expected_nodes=$(kubectl get nodes --no-headers | wc -l)
[[ ${#server_ips[@]} -eq "$expected_nodes" ]]
[[ ${#clients[@]} -eq "$expected_nodes" ]]

for client in "${clients[@]}"; do
  [[ $(kubectl exec -n "$namespace" "$client" -- \
    wget -qO- http://connectivity-server:8080/) == ok ]]
  for server_ip in "${server_ips[@]}"; do
    [[ $(kubectl exec -n "$namespace" "$client" -- \
      wget -qO- "http://${server_ip}:8080/") == ok ]]
  done
done

echo "connectivity passed: ${#clients[@]} clients x ${#server_ips[@]} server pod IPs plus ClusterIP service"
