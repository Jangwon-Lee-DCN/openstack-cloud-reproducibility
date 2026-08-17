#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
NAMESPACE=${NAMESPACE:-openstack}
REGISTRY=${REGISTRY:-registry.dcn.ssu.ac.kr/openstack}
BUILD_ID=${BUILD_ID:-$(git -C "$REPO_ROOT" rev-parse --short=12 HEAD)-$(date -u +%Y%m%d%H%M%S)}
VPC_DASHBOARD_REPO=${VPC_DASHBOARD_REPO:-$REPO_ROOT/../openstack-vpc-dashboard}
TELEMETRY_DASHBOARD_REPO=${TELEMETRY_DASHBOARD_REPO:-$REPO_ROOT/../openstack-telemetry-dashboard}
S3_DASHBOARD_REPO=${S3_DASHBOARD_REPO:-$REPO_ROOT/../openstack-s3-dashboard}
KANIKO_IMAGE=gcr.io/kaniko-project/executor:v1.23.2-debug@sha256:c3109d5926a997b100c4343944e06c6b30a6804b2f9abe0994d3de6ef92b028e
JOB=source-rebuild-horizon-complete

for command in kubectl sops git tar python3; do
  command -v "$command" >/dev/null || { echo "missing command: $command" >&2; exit 1; }
done
for repo in "$VPC_DASHBOARD_REPO" "$TELEMETRY_DASHBOARD_REPO" "$S3_DASHBOARD_REPO"; do
  git -C "$repo" diff --quiet && git -C "$repo" diff --cached --quiet || {
    echo "refusing to build from dirty source repository: $repo" >&2; exit 1;
  }
done

WORK_DIR=$(mktemp -d /tmp/dcn-horizon-rebuild.XXXXXX)
cleanup() { rm -rf "$WORK_DIR"; }
trap cleanup EXIT
context="$WORK_DIR/context"
mkdir -p "$context/octavia-workflow" "$context/project-selfservice" "$context/magnum-ui" "$context/enabled" "$context/service_catalog"

(cd "$VPC_DASHBOARD_REPO" && python3 -m build && make verify-wheel)
(cd "$TELEMETRY_DASHBOARD_REPO" && python3 -m build && make verify)
(cd "$S3_DASHBOARD_REPO" && python3 -m build && make verify)

cp "$REPO_ROOT/images/horizon-complete/Dockerfile" "$context/Dockerfile"
cp "$REPO_ROOT/images/horizon-complete/platform_navigation.py" "$context/platform_navigation.py"
cp "$REPO_ROOT/images/horizon-complete/enabled/_9999_platform_navigation.py" "$context/enabled/_9999_platform_navigation.py"
cp "$REPO_ROOT/images/horizon-complete/enabled/_1380_dcn_service_catalog.py" "$context/enabled/_1380_dcn_service_catalog.py"
cp -a "$REPO_ROOT/images/horizon-complete/service_catalog/." "$context/service_catalog/"
cp "$REPO_ROOT/deploy/config/tenant-service-catalog.yaml" "$context/tenant-service-catalog.yaml"
cp "$VPC_DASHBOARD_REPO"/dist/openstack_vpc_dashboard-*.whl "$context/openstack_vpc_dashboard.whl"
cp "$TELEMETRY_DASHBOARD_REPO"/dist/openstack_telemetry_dashboard-*.whl "$context/openstack_telemetry_dashboard.whl"
cp "$S3_DASHBOARD_REPO"/dist/openstack_s3_dashboard-*.whl "$context/openstack_s3_dashboard.whl"
cp "$REPO_ROOT/images/horizon-octavia-dashboard"/{model.service.js,loadbalancer.html,loadbalancer.controller.js,listener.html,listener.controller.js,pool.html,pool.controller.js} "$context/octavia-workflow/"
cp -a "$REPO_ROOT/images/horizon-project-selfservice-dashboard/pkg/." "$context/project-selfservice/"
cp "$REPO_ROOT/images/horizon-magnum-dashboard/enhance_magnum_ui.py" "$context/magnum-ui/"
cp -a "$REPO_ROOT/images/horizon-magnum-dashboard/overlay" "$context/magnum-ui/overlay"

archive="$WORK_DIR/context.tar.gz"
tar --sort=name --mtime='UTC 2020-01-01' --owner=0 --group=0 --numeric-owner -C "$context" -czf "$archive" .
# Derive the disposable builder credential from Harbor's live administrator
# Secret. This follows the full image builder and survives Harbor password
# rotation without storing or printing plaintext credentials.
kubectl -n harbor get secret harbor-admin-password -o json |
  python3 -c 'import base64,json,sys; s=json.load(sys.stdin); p=base64.b64decode(s["data"]["HARBOR_ADMIN_PASSWORD"]).decode(); cfg={"auths":{"registry.dcn.ssu.ac.kr":{"username":"admin","password":p,"auth":base64.b64encode(("admin:"+p).encode()).decode()}}}; out={"apiVersion":"v1","kind":"Secret","metadata":{"name":"telemetry-harbor-push","namespace":sys.argv[1]},"type":"kubernetes.io/dockerconfigjson","data":{".dockerconfigjson":base64.b64encode(json.dumps(cfg,separators=(",", ":")).encode()).decode()}}; print(json.dumps(out))' "$NAMESPACE" |
  kubectl apply -f - >/dev/null
kubectl delete job "$JOB" -n "$NAMESPACE" --ignore-not-found --wait=true
kubectl delete configmap "$JOB" -n "$NAMESPACE" --ignore-not-found --wait=true
kubectl create configmap "$JOB" -n "$NAMESPACE" --from-file=context.tar.gz="$archive"

image="$REGISTRY/horizon:source-$BUILD_ID"
kubectl apply -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata: {name: $JOB, namespace: $NAMESPACE}
spec:
  backoffLimit: 0
  ttlSecondsAfterFinished: 86400
  template:
    spec:
      restartPolicy: Never
      # Image builds must not depend on the cluster DNS view of the site's
      # Harbor name. Use the routed registry VIP reachable from every rack.
      hostAliases:
        - ip: 10.67.10.4
          hostnames: [registry.dcn.ssu.ac.kr]
      nodeSelector: {openstack-control-plane: enabled}
      tolerations:
        - {key: node-role.kubernetes.io/control-plane, operator: Exists, effect: NoSchedule}
      initContainers:
        - name: extract-context
          image: $KANIKO_IMAGE
          command: [/busybox/sh, -c, 'cd /workspace && /busybox/tar xzf /archive/context.tar.gz']
          volumeMounts:
            - {name: archive, mountPath: /archive, readOnly: true}
            - {name: workspace, mountPath: /workspace}
      containers:
        - name: kaniko
          image: $KANIKO_IMAGE
          args:
            - --context=dir:///workspace
            - --dockerfile=/workspace/Dockerfile
            - --destination=$image
            - --digest-file=/dev/termination-log
            - --skip-tls-verify
            - --snapshot-mode=redo
          volumeMounts:
            - {name: workspace, mountPath: /workspace, readOnly: true}
            - {name: registry-auth, mountPath: /kaniko/.docker, readOnly: true}
      volumes:
        - {name: archive, configMap: {name: $JOB}}
        - {name: workspace, emptyDir: {}}
        - name: registry-auth
          secret: {secretName: telemetry-harbor-push, items: [{key: .dockerconfigjson, path: config.json}]}
EOF

kubectl wait -n "$NAMESPACE" --for=condition=complete "job/$JOB" --timeout=30m
digest=$(kubectl get pod -n "$NAMESPACE" -l "job-name=$JOB" -o jsonpath='{.items[0].status.containerStatuses[0].state.terminated.message}')
[[ "$digest" == sha256:* ]] || { echo "Horizon build did not emit a digest: $digest" >&2; exit 1; }
printf 'horizon=%s@%s\n' "$image" "$digest"
