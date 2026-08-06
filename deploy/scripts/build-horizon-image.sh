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
mkdir -p "$context/octavia-workflow" "$context/project-selfservice" "$context/magnum-ui" "$context/enabled"

(cd "$VPC_DASHBOARD_REPO" && python3 -m build && make verify-wheel)
(cd "$TELEMETRY_DASHBOARD_REPO" && python3 -m build && make verify)
(cd "$S3_DASHBOARD_REPO" && python3 -m build && make verify)

cp "$REPO_ROOT/images/horizon-complete/Dockerfile" "$context/Dockerfile"
cp "$REPO_ROOT/images/horizon-complete/platform_navigation.py" "$context/platform_navigation.py"
cp "$REPO_ROOT/images/horizon-complete/enabled/_9999_platform_navigation.py" "$context/enabled/_9999_platform_navigation.py"
cp "$VPC_DASHBOARD_REPO"/dist/openstack_vpc_dashboard-*.whl "$context/openstack_vpc_dashboard.whl"
cp "$TELEMETRY_DASHBOARD_REPO"/dist/openstack_telemetry_dashboard-*.whl "$context/openstack_telemetry_dashboard.whl"
cp "$S3_DASHBOARD_REPO"/dist/openstack_s3_dashboard-*.whl "$context/openstack_s3_dashboard.whl"
cp "$REPO_ROOT/images/horizon-octavia-dashboard"/{model.service.js,loadbalancer.html,loadbalancer.controller.js,listener.html,listener.controller.js,pool.html,pool.controller.js} "$context/octavia-workflow/"
cp -a "$REPO_ROOT/images/horizon-project-selfservice-dashboard/pkg/." "$context/project-selfservice/"
cp "$REPO_ROOT/images/horizon-magnum-dashboard/enhance_magnum_ui.py" "$context/magnum-ui/"
cp -a "$REPO_ROOT/images/horizon-magnum-dashboard/overlay" "$context/magnum-ui/overlay"

archive="$WORK_DIR/context.tar.gz"
tar --sort=name --mtime='UTC 2020-01-01' --owner=0 --group=0 --numeric-owner -C "$context" -czf "$archive" .
sops -d "$REPO_ROOT/deploy/secrets/telemetry-harbor-push.secret.sops.yaml" | kubectl apply -f -
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
