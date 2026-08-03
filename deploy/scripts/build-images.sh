#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
NAMESPACE=${NAMESPACE:-openstack}
REGISTRY=${REGISTRY:-registry.dcn.ssu.ac.kr/openstack}
BUILD_ID=${BUILD_ID:-$(git -C "$REPO_ROOT" rev-parse --short=12 HEAD)}
VPC_DASHBOARD_REPO=${VPC_DASHBOARD_REPO:-$REPO_ROOT/../openstack-vpc-dashboard}
VPC_CONTROL_PLANE_REPO=${VPC_CONTROL_PLANE_REPO:-$REPO_ROOT/../vpc-control-plane}
MAGNUM_GITOPS_REPO=${MAGNUM_GITOPS_REPO:-$REPO_ROOT/../magnum-capi-gitops}
RESULT_FILE=${RESULT_FILE:-$REPO_ROOT/deploy/generated/rebuilt-images.env}
KANIKO_IMAGE=gcr.io/kaniko-project/executor:v1.23.2-debug@sha256:c3109d5926a997b100c4343944e06c6b30a6804b2f9abe0994d3de6ef92b028e

for command in kubectl sops git tar sha256sum go; do
  command -v "$command" >/dev/null || { echo "missing command: $command" >&2; exit 1; }
done
for repo in "$VPC_DASHBOARD_REPO" "$VPC_CONTROL_PLANE_REPO" "$MAGNUM_GITOPS_REPO"; do
  git -C "$repo" diff --quiet && git -C "$repo" diff --cached --quiet || {
    echo "refusing to build from dirty source repository: $repo" >&2; exit 1;
  }
done

WORK_DIR=$(mktemp -d /tmp/dcn-image-rebuild.XXXXXX)
cleanup() { rm -rf "$WORK_DIR"; }
trap cleanup EXIT
mkdir -p "$(dirname "$RESULT_FILE")"
: > "$RESULT_FILE"

sops -d "$REPO_ROOT/deploy/secrets/telemetry-harbor-push.secret.sops.yaml" | kubectl apply -f -

build_context() {
  local name=$1 context=$2 image=$3 job="source-rebuild-${name}"
  local archive="$WORK_DIR/${name}.tar.gz" digest
  tar --sort=name --mtime='UTC 2020-01-01' --owner=0 --group=0 --numeric-owner -C "$context" -czf "$archive" .
  kubectl create configmap "$job" -n "$NAMESPACE" --from-file=context.tar.gz="$archive" --dry-run=client -o yaml | kubectl apply -f -
  kubectl delete job "$job" -n "$NAMESPACE" --ignore-not-found --wait=true
  kubectl apply -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata: {name: $job, namespace: $NAMESPACE}
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
        - {name: archive, configMap: {name: $job}}
        - {name: workspace, emptyDir: {}}
        - name: registry-auth
          secret: {secretName: telemetry-harbor-push, items: [{key: .dockerconfigjson, path: config.json}]}
EOF
  kubectl wait -n "$NAMESPACE" --for=condition=complete "job/$job" --timeout=30m
  digest=$(kubectl get pod -n "$NAMESPACE" -l "job-name=$job" -o jsonpath='{.items[0].status.containerStatuses[0].state.terminated.message}')
  [[ "$digest" == sha256:* ]] || { echo "$name did not emit a digest: $digest" >&2; exit 1; }
  printf '%s=%s@%s\n' "${name//-/_}" "$image" "$digest" | tee -a "$RESULT_FILE"
}

simple_context() {
  local component=$1 image_name=${2:-$1} context="$WORK_DIR/$component"
  mkdir -p "$context"
  cp -a "$REPO_ROOT/images/$component/." "$context/"
  build_context "$component" "$context" "$REGISTRY/$image_name:source-$BUILD_ID"
}

# Images whose parents are all public and digest-pinned.
for component in gnocchi ceilometer aodh keycloak; do simple_context "$component"; done
simple_context keystone-oidc keystone
simple_context neutron-fwaas neutron
simple_context octavia-ovn octavia

# Magnum base must precede the GitOps driver image. The generated result file
# supplies its immutable digest to the second Dockerfile, removing any Harbor
# bootstrap dependency.
simple_context magnum-capi magnum
magnum_ref=$(awk -F= '$1=="magnum_capi"{print $2}' "$RESULT_FILE")
magnum_context="$WORK_DIR/magnum-capi-gitops"
mkdir -p "$magnum_context"
cp "$REPO_ROOT/images/magnum-capi-gitops/Dockerfile" "$magnum_context/Dockerfile"
sed -i "s#registry.dcn.ssu.ac.kr/openstack/magnum@sha256:[a-f0-9]*#$magnum_ref#" "$magnum_context/Dockerfile"
cp -a "$MAGNUM_GITOPS_REPO/magnum-driver" "$magnum_context/magnum-driver"
build_context magnum-capi-gitops "$magnum_context" "$REGISTRY/magnum-capi-gitops:source-$BUILD_ID"

writer_context="$WORK_DIR/magnum-capi-repository-writer"
mkdir -p "$writer_context"
cp "$REPO_ROOT/images/magnum-capi-gitops/repository-writer.Dockerfile" "$writer_context/Dockerfile"
cp -a "$MAGNUM_GITOPS_REPO/magnum-driver" "$writer_context/magnum-driver"
cp -a "$MAGNUM_GITOPS_REPO/repository-writer" "$writer_context/repository-writer"
mkdir -p "$writer_context/vendor/capi-helm-charts"
cp -a "$MAGNUM_GITOPS_REPO/vendor/capi-helm-charts/openstack-cluster" "$writer_context/vendor/capi-helm-charts/openstack-cluster"
build_context magnum-capi-repository-writer "$writer_context" "$REGISTRY/magnum-capi-repository-writer:source-$BUILD_ID"

# Build the VPC binaries from the locked Git checkout, then package only the
# binaries in digest-pinned runtime images.
(cd "$VPC_CONTROL_PLANE_REPO" && CGO_ENABLED=0 GOOS=linux go build -trimpath -o "$WORK_DIR/manager" ./cmd/main.go)
(cd "$VPC_CONTROL_PLANE_REPO" && CGO_ENABLED=0 GOOS=linux go build -trimpath -o "$WORK_DIR/apiserver" ./cmd/apiserver)
for item in manager:vpc-control-plane:manager-runtime apiserver:vpc-facade:apiserver-runtime; do
  IFS=: read -r binary image runtime <<<"$item"
  context="$WORK_DIR/$image"; mkdir -p "$context/dist"
  cp "$WORK_DIR/$binary" "$context/dist/$binary"
  cp "$VPC_CONTROL_PLANE_REPO/Dockerfile.$runtime" "$context/Dockerfile"
  build_context "$image" "$context" "$REGISTRY/$image:source-$BUILD_ID"
done

# One upstream-rooted Horizon image replaces the historical private-image
# layer chain. The wheel must be rebuilt from the locked dashboard checkout.
(cd "$VPC_DASHBOARD_REPO" && python3 -m build && make verify-wheel)
horizon_context="$WORK_DIR/horizon-complete"
mkdir -p "$horizon_context/octavia-workflow" "$horizon_context/project-selfservice"
cp "$REPO_ROOT/images/horizon-complete/Dockerfile" "$horizon_context/Dockerfile"
cp "$VPC_DASHBOARD_REPO"/dist/openstack_vpc_dashboard-*.whl "$horizon_context/openstack_vpc_dashboard.whl"
cp "$REPO_ROOT/images/horizon-octavia-dashboard"/{model.service.js,loadbalancer.html,loadbalancer.controller.js,listener.html,listener.controller.js,pool.html,pool.controller.js} "$horizon_context/octavia-workflow/"
cp -a "$REPO_ROOT/images/horizon-project-selfservice-dashboard/pkg/." "$horizon_context/project-selfservice/"
build_context horizon-complete "$horizon_context" "$REGISTRY/horizon:source-$BUILD_ID"

# Build this last so concurrent application development cannot accidentally be
# hidden by a successful infrastructure-only run.
simple_context project-facade

# CAPO's source tree is larger than Kubernetes' ConfigMap limit. Its dedicated
# Job fetches the exact (not merely tagged) upstream commit, applies the one
# recorded patch, and builds directly from the shared emptyDir.
kubectl delete job capo-image-build -n "$NAMESPACE" --ignore-not-found --wait=true
kubectl apply -f "$REPO_ROOT/prerequisites/cluster-api/management-cluster/manifests/capo-image-build.yaml"
kubectl wait -n "$NAMESPACE" --for=condition=complete job/capo-image-build --timeout=30m
capo_digest=$(kubectl get pod -n "$NAMESPACE" -l job-name=capo-image-build -o jsonpath='{.items[0].status.containerStatuses[0].state.terminated.message}')
[[ "$capo_digest" == sha256:* ]] || { echo "CAPO did not emit a digest: $capo_digest" >&2; exit 1; }
printf 'capo_controller=%s@%s\n' "$REGISTRY/capo-controller:source-v0.14.6-poc1" "$capo_digest" | tee -a "$RESULT_FILE"

echo "All source builds completed. Immutable references: $RESULT_FILE"
echo "Run deploy/scripts/apply-rebuilt-image-lock.py to preview, then rerun with --apply and commit the reviewed pins."
