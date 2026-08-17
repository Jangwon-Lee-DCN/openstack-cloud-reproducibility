#!/usr/bin/env bash
set -euo pipefail
namespace=${OPENSTACK_NAMESPACE:-openstack}
pvc=glance-images-restore-drill
job=glance-image-restore-drill
snapshot=${GLANCE_SNAPSHOT:-$(kubectl -n "$namespace" get volumesnapshot -l dcn.ssu.ac.kr/backup=glance-images --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1:].metadata.name}')}
[[ -n $snapshot ]] || { echo 'no Glance backup VolumeSnapshot found' >&2; exit 1; }
[[ $(kubectl -n "$namespace" get volumesnapshot "$snapshot" -o jsonpath='{.status.readyToUse}') == true ]] || {
  echo "$snapshot is not ReadyToUse" >&2; exit 1;
}
cleanup() {
  kubectl -n "$namespace" delete job "$job" --ignore-not-found --wait=true >/dev/null
  kubectl -n "$namespace" delete pvc "$pvc" --ignore-not-found --wait=true >/dev/null
}
trap cleanup EXIT
cleanup
kubectl apply -f - <<EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata: {name: $pvc, namespace: $namespace, labels: {dcn.ssu.ac.kr/drill: glance-restore}}
spec:
  storageClassName: powerstore-rwo-single-path
  accessModes: [ReadWriteOnce]
  resources: {requests: {storage: 100Gi}}
  dataSource: {apiGroup: snapshot.storage.k8s.io, kind: VolumeSnapshot, name: $snapshot}
---
apiVersion: batch/v1
kind: Job
metadata: {name: $job, namespace: $namespace}
spec:
  backoffLimit: 0
  activeDeadlineSeconds: 1800
  template:
    metadata: {labels: {application: glance, component: image-restore-drill}}
    spec:
      restartPolicy: Never
      automountServiceAccountToken: false
      nodeSelector: {openstack-compute-node: enabled}
      containers:
        - name: verify
          image: quay.io/airshipit/openstack-client@sha256:8a402a50ecf2afe14f580ad2bae17433605c29063b0d5e2c0f3d3c962d13c656
          envFrom: [{secretRef: {name: keystone-keystone-admin}}]
          command: [bash, -ec]
          args:
            - |
              count=0
              while read -r id; do
                expected=\$(openstack image show "\$id" -f json | python3 -c 'import json,sys; d=json.load(sys.stdin); p=d.get("properties",{}); print(p.get("os_hash_value", d.get("os_hash_value", "")))')
                file="/restore/\$id"
                [[ -f "\$file" ]] || { echo "missing image file: \$id" >&2; exit 1; }
                actual=\$(sha512sum "\$file" | awk '{print \$1}')
                [[ -n "\$expected" && "\$actual" == "\$expected" ]] || { echo "checksum mismatch: \$id" >&2; exit 1; }
                count=\$((count+1))
              done < <({ openstack image list --status active -f value -c ID; openstack image list --status active --hidden -f value -c ID; } | sort -u)
              echo "PASS: snapshot $snapshot restored and \$count active image checksums matched"
          volumeMounts: [{name: restore, mountPath: /restore, readOnly: true}]
          securityContext: {allowPrivilegeEscalation: false, capabilities: {drop: [ALL]}, runAsNonRoot: true, runAsUser: 65534, seccompProfile: {type: RuntimeDefault}}
      volumes: [{name: restore, persistentVolumeClaim: {claimName: $pvc, readOnly: true}}]
EOF
for _ in $(seq 1 900); do
  complete=$(kubectl -n "$namespace" get job "$job" -o jsonpath='{.status.conditions[?(@.type=="Complete")].status}')
  failed=$(kubectl -n "$namespace" get job "$job" -o jsonpath='{.status.conditions[?(@.type=="Failed")].status}')
  [[ $complete == True ]] && break
  if [[ $failed == True ]]; then kubectl -n "$namespace" logs "job/$job" || true; exit 1; fi
  sleep 2
done
[[ ${complete:-} == True ]] || { kubectl -n "$namespace" logs "job/$job" || true; exit 1; }
kubectl -n "$namespace" logs "job/$job"
