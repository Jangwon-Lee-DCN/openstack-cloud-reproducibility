#!/usr/bin/env bash
set -euo pipefail

namespace=${OPENSTACK_NAMESPACE:-openstack}
job=octavia-node-port-reconcile
nodes=$(kubectl get nodes -l openstack-network-node=enabled \
  -o jsonpath='{range .items[*]}{.metadata.name}{" "}{end}')
test -n "${nodes// }"

kubectl -n "$namespace" delete job "$job" --ignore-not-found --wait=true
cat <<EOF | kubectl -n "$namespace" apply -f -
apiVersion: batch/v1
kind: Job
metadata:
  name: ${job}
spec:
  backoffLimit: 0
  ttlSecondsAfterFinished: 600
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: reconcile
          image: quay.io/airshipit/openstack-client:2026.1-ubuntu_noble
          envFrom:
            - secretRef:
                name: octavia-keystone-admin
          command: [/bin/bash, -ceu]
          args:
            - |
              for node in ${nodes}; do
                for role in health-manager worker; do
                  port="octavia-\${role}-port-\${node}"
                  if openstack port show "\${port}" >/dev/null 2>&1; then
                    continue
                  fi
                  if [[ "\${role}" == health-manager ]]; then
                    security_group=lb-health-mgr-sec-grp
                    device_owner=Octavia:health-mgr
                  else
                    security_group=lb-worker-sec-grp
                    device_owner=Octavia:worker
                  fi
                  openstack port create \
                    --network lb-mgmt-net \
                    --security-group "\${security_group}" \
                    --device-owner "\${device_owner}" \
                    --host "\${node}" \
                    "\${port}" >/dev/null
                done
              done
EOF
kubectl -n "$namespace" wait --for=condition=complete "job/$job" --timeout=5m
kubectl -n "$namespace" logs "job/$job"
