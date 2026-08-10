#!/usr/bin/env bash
set -euo pipefail

NAMESPACE=${NAMESPACE:-openstack}
CLIENT_IMAGE=${OPENSTACK_CLIENT_IMAGE:-quay.io/airshipit/openstack-client:2026.1-ubuntu_noble}
MOUNT_IMAGE=${NFS_TEST_IMAGE:-ubuntu:24.04}
TYPE=powerstore-nfs
SHARE=powerstore-qualification
SNAPSHOT=powerstore-qualification-snapshot
ACCESS_IP=${POWERSTORE_NFS_CLIENT_IP:-10.70.20.21}

cleanup() {
  kubectl delete pod -n "$NAMESPACE" powerstore-manila-client --ignore-not-found --wait=false >/dev/null
  kubectl delete job -n "$NAMESPACE" powerstore-manila-mount --ignore-not-found --wait=false >/dev/null
}
trap cleanup EXIT

kubectl get deployment -n "$NAMESPACE" manila-share >/dev/null
kubectl rollout status -n "$NAMESPACE" deployment/manila-share --timeout=10m
kubectl delete pod -n "$NAMESPACE" powerstore-manila-client --ignore-not-found >/dev/null
kubectl apply -f - <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: powerstore-manila-client
  namespace: $NAMESPACE
spec:
  restartPolicy: Never
  containers:
    - name: client
      image: $CLIENT_IMAGE
      command: [sleep, "3600"]
      envFrom:
        - secretRef:
            name: keystone-keystone-admin
EOF
kubectl wait -n "$NAMESPACE" --for=condition=Ready pod/powerstore-manila-client --timeout=5m

osc() { kubectl exec -n "$NAMESPACE" powerstore-manila-client -- openstack "$@"; }
if ! osc share type show "$TYPE" >/dev/null 2>&1; then
  osc share type create "$TYPE" false --snapshot-support true \
    --create-share-from-snapshot-support true --revert-to-snapshot-support true >/dev/null
fi
osc share type set "$TYPE" --extra-specs share_backend_name=POWERSTORE >/dev/null
osc share create NFS 3 --name "$SHARE" --share-type "$TYPE" --wait >/dev/null
access_id=$(osc share access create "$SHARE" ip "$ACCESS_IP" --access-level rw -f value -c id)

export_location=$(osc share export location list "$SHARE" -f value -c Path | head -n1)
[[ "$export_location" == 10.70.20.10:* ]] || {
  echo "unexpected PowerStore export location: $export_location" >&2
  exit 1
}

kubectl delete job -n "$NAMESPACE" powerstore-manila-mount --ignore-not-found >/dev/null
kubectl apply -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: powerstore-manila-mount
  namespace: $NAMESPACE
spec:
  template:
    spec:
      restartPolicy: Never
      hostNetwork: true
      nodeSelector:
        kubernetes.io/hostname: dcn-1a-controller-0
      tolerations:
        - key: node-role.kubernetes.io/control-plane
          operator: Exists
          effect: NoSchedule
      containers:
        - name: powerstore-manila-mount
          image: $MOUNT_IMAGE
          securityContext:
            privileged: true
          command: [bash, -ceu]
          args:
            - >-
              apt-get update >/dev/null && apt-get install -y nfs-common >/dev/null;
              mkdir -p /mnt/share; mount -t nfs '$export_location' /mnt/share;
              printf powerstore-manila-ok >/mnt/share/qualification; sync;
              test "\$(cat /mnt/share/qualification)" = powerstore-manila-ok;
              umount /mnt/share
EOF
kubectl wait -n "$NAMESPACE" --for=condition=complete job/powerstore-manila-mount --timeout=10m

osc share snapshot create "$SHARE" --name "$SNAPSHOT" --wait >/dev/null
osc share snapshot delete "$SNAPSHOT" --wait >/dev/null
osc share access delete "$SHARE" "$access_id" >/dev/null
osc share delete "$SHARE" --wait >/dev/null
echo "PowerStoreOS 2.1 Manila create/access/mount/write/snapshot/delete qualification: PASS"
