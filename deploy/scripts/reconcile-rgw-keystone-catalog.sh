#!/usr/bin/env bash
set -euo pipefail

store=openstack-object-store
region=seoul-ssu-1
client_image=quay.io/airshipit/openstack-client:2026.1-ubuntu_noble
source_secret=cinder-keystone-swift
rgw_secret=rgw-keystone-service-user
root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)

kubectl -n openstack get secret "$source_secret" >/dev/null
kubectl -n openstack get secret "$source_secret" -o json |
  python3 -c 'import json,sys; x=json.load(sys.stdin); x["metadata"]={"name":sys.argv[1],"namespace":"rook-ceph"}; [x.pop(k,None) for k in ("status",)]; print(json.dumps(x))' "$rgw_secret" |
  kubectl apply -f - >/dev/null

kubectl -n rook-ceph patch cephobjectstore "$store" --type=merge -p "$(cat <<EOF
{"spec":{"auth":{"keystone":{"url":"http://keystone-api.openstack.svc.cluster.local:5000/v3","serviceUserSecretName":"$rgw_secret","acceptedRoles":["reader","member","admin","service"],"implicitTenants":"swift","tokenCacheSize":500,"revocationInterval":300}}}}
EOF
)"
kubectl -n rook-ceph apply -f "$root/deploy/manifests/rgw-swift-route.yaml"
kubectl -n rook-ceph rollout status deployment/rook-ceph-rgw-$store-a --timeout=15m

# The catalog is reconciled only inside this Job, after a real Keystone token
# has listed its Swift account through RGW. A dead endpoint can never be
# published by a merely successful Kubernetes rollout.
kubectl -n openstack delete job rgw-keystone-catalog --ignore-not-found --wait=true >/dev/null
cat <<EOF | kubectl apply -f - >/dev/null
apiVersion: batch/v1
kind: Job
metadata: {name: rgw-keystone-catalog, namespace: openstack}
spec:
  backoffLimit: 0
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: reconcile
          image: $client_image
          envFrom: [{secretRef: {name: $source_secret}}]
          command: [/bin/bash, -ceu]
          args:
            - |
              token="\$(openstack token issue -f value -c id)"
              project_id="\$(openstack token issue -f value -c project_id)"
              python3 - "\$token" "\$project_id" <<'PY'
              import sys, urllib.request
              token, project = sys.argv[1:]
              url = 'http://rook-ceph-rgw-openstack-object-store.rook-ceph.svc.cluster.local/swift/v1/AUTH_' + project
              with urllib.request.urlopen(urllib.request.Request(url, headers={'X-Auth-Token': token}), timeout=10) as r:
                  assert 200 <= r.status < 300
              PY
              service_id="\$(openstack service list --type object-store -f value -c ID | head -1)"
              if [[ -z "\$service_id" ]]; then
                service_id="\$(openstack service create --name swift object-store -f value -c id)"
              fi
              while read -r endpoint_id; do
                [[ -z "\$endpoint_id" ]] || openstack endpoint delete "\$endpoint_id"
              done < <(openstack endpoint list --service "\$service_id" --region $region -f value -c ID)
              openstack endpoint create --region $region "\$service_id" public 'https://s3.cloud.dcn.ssu.ac.kr/swift/v1/AUTH_%(project_id)s'
              openstack endpoint create --region $region "\$service_id" internal 'http://rook-ceph-rgw-openstack-object-store.rook-ceph.svc.cluster.local/swift/v1/AUTH_%(project_id)s'
              openstack endpoint create --region $region "\$service_id" admin 'http://rook-ceph-rgw-openstack-object-store.rook-ceph.svc.cluster.local/swift/v1/AUTH_%(project_id)s'
              test "\$(openstack endpoint list --service "\$service_id" --region $region -f value -c ID | wc -l)" -eq 3
EOF
kubectl -n openstack wait --for=condition=complete job/rgw-keystone-catalog --timeout=10m
