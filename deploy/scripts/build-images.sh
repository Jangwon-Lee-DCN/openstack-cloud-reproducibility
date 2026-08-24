#!/usr/bin/env bash
set -euo pipefail

# Once the shared queue is installed, direct invocations can race with other
# sessions and overwrite a newer source tag. The queue runner supplies the
# request UUID. Fresh rebuild hosts without the service retain the bootstrap
# path, and an operator can stop the service before an explicitly reviewed
# recovery build.
if systemctl is-active --quiet dcn-image-build-queue.service 2>/dev/null &&
   [[ -z ${DCN_IMAGE_BUILD_QUEUE_TASK:-} ]]; then
  echo "direct image builds are disabled while dcn-image-build-queue.service is active" >&2
  echo "submit the build with dcn-image-build; do not stop or bypass the queue for routine work" >&2
  exit 2
fi

REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
NAMESPACE=${NAMESPACE:-openstack}
REGISTRY=${REGISTRY:-registry.dcn.ssu.ac.kr/openstack}
REGISTRY_HOST=${REGISTRY_HOST:-${REGISTRY%%/*}}
REGISTRY_IP=${REGISTRY_IP:-$(getent ahostsv4 "$REGISTRY_HOST" | awk 'NR == 1 {print $1}')}
[[ -n "$REGISTRY_IP" ]] || { echo "cannot resolve registry host $REGISTRY_HOST" >&2; exit 1; }
BUILD_ID=${BUILD_ID:-$(git -C "$REPO_ROOT" rev-parse --short=12 HEAD)}
VPC_DASHBOARD_REPO=${VPC_DASHBOARD_REPO:-$REPO_ROOT/../openstack-vpc-dashboard}
VPC_CONTROL_PLANE_REPO=${VPC_CONTROL_PLANE_REPO:-$REPO_ROOT/../vpc-control-plane}
MAGNUM_GITOPS_REPO=${MAGNUM_GITOPS_REPO:-$REPO_ROOT/../magnum-capi-gitops}
TELEMETRY_DASHBOARD_REPO=${TELEMETRY_DASHBOARD_REPO:-$REPO_ROOT/../openstack-telemetry-dashboard}
S3_DASHBOARD_REPO=${S3_DASHBOARD_REPO:-$REPO_ROOT/../openstack-s3-dashboard}
FLYT_ADAPTER_REPO=${FLYT_ADAPTER_REPO:-$REPO_ROOT/../openstack-flyt-adapter}
FLYT_MANAGED_RUNTIME_REPO=${FLYT_MANAGED_RUNTIME_REPO:-$REPO_ROOT/../flyt-managed-runtime}
NOVA_EXTENDED_COMPUTE_REPO=${NOVA_EXTENDED_COMPUTE_REPO:-$REPO_ROOT/../nova-extended-compute}
RESULT_FILE=${RESULT_FILE:-$REPO_ROOT/deploy/generated/rebuilt-images.env}
REGISTRY_SECRET=${REGISTRY_SECRET:-telemetry-harbor-push}
PYTHON_BINARY=${PYTHON_BINARY:-python3}
if [[ "$PYTHON_BINARY" == python3 && -x "$REPO_ROOT/../../.venv/bin/python" ]]; then
  PYTHON_BINARY="$REPO_ROOT/../../.venv/bin/python"
fi
# Space-separated source component names. Empty means the complete rebuild.
BUILD_COMPONENTS=${BUILD_COMPONENTS:-}
KANIKO_IMAGE=gcr.io/kaniko-project/executor:v1.23.2-debug@sha256:c3109d5926a997b100c4343944e06c6b30a6804b2f9abe0994d3de6ef92b028e

for command in kubectl sops git tar sha256sum go; do
  command -v "$command" >/dev/null || { echo "missing command: $command" >&2; exit 1; }
done
if [[ -z "$BUILD_COMPONENTS" ]]; then
  for repo in "$VPC_DASHBOARD_REPO" "$VPC_CONTROL_PLANE_REPO" "$MAGNUM_GITOPS_REPO" "$TELEMETRY_DASHBOARD_REPO" "$S3_DASHBOARD_REPO"; do
    git -C "$repo" diff --quiet && git -C "$repo" diff --cached --quiet || {
      echo "refusing to build from dirty source repository: $repo" >&2; exit 1;
    }
  done
fi

WORK_DIR=$(mktemp -d /tmp/dcn-image-rebuild.XXXXXX)
cleanup() { rm -rf "$WORK_DIR"; }
trap cleanup EXIT
mkdir -p "$(dirname "$RESULT_FILE")"
: > "$RESULT_FILE"

if [[ "$REGISTRY_SECRET" == telemetry-harbor-push ]]; then
  # Harbor is itself installed by the platform. Derive the build credential
  # from its live admin Secret so a rotated password cannot leave a stale
  # encrypted dockerconfig blocking a reproducible rebuild. No credential is
  # written to disk or printed.
  kubectl -n harbor get secret harbor-admin-password -o json |
    "$PYTHON_BINARY" -c 'import base64,json,sys; s=json.load(sys.stdin); p=base64.b64decode(s["data"]["HARBOR_ADMIN_PASSWORD"]).decode(); cfg={"auths":{"registry.dcn.ssu.ac.kr":{"username":"admin","password":p,"auth":base64.b64encode(("admin:"+p).encode()).decode()}}}; out={"apiVersion":"v1","kind":"Secret","metadata":{"name":sys.argv[1],"namespace":sys.argv[2]},"type":"kubernetes.io/dockerconfigjson","data":{".dockerconfigjson":base64.b64encode(json.dumps(cfg,separators=(",", ":")).encode()).decode()}}; print(json.dumps(out))' "$REGISTRY_SECRET" "$NAMESPACE" |
    kubectl apply -f - >/dev/null
fi

selected() {
  [[ -z "$BUILD_COMPONENTS" || " $BUILD_COMPONENTS " == *" $1 "* ]]
}

build_context() {
  local name=$1 context=$2 image=$3 job safe_build_id
  safe_build_id=$(printf '%s' "$BUILD_ID" | tr -cs 'a-zA-Z0-9-' '-' | tr 'A-Z' 'a-z' | cut -c1-20)
  job="source-rebuild-${name}-${safe_build_id}"
  local archive="$WORK_DIR/${name}.tar.gz" digest
  tar --sort=name --mtime='UTC 2020-01-01' --owner=0 --group=0 --numeric-owner -C "$context" -czf "$archive" .
  kubectl delete job "$job" -n "$NAMESPACE" --ignore-not-found --wait=true
  # A binary build context can exceed the 256 KiB annotation limit added by
  # `kubectl apply`. Recreate this disposable, job-scoped ConfigMap directly.
  kubectl delete configmap "$job" -n "$NAMESPACE" --ignore-not-found --wait=true
  kubectl create configmap "$job" -n "$NAMESPACE" --from-file=context.tar.gz="$archive"
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
      # The private registry zone is served to infrastructure hosts, while
      # cluster DNS intentionally forwards public queries. Keep source builds
      # deterministic by carrying the host-resolved registry address into the
      # disposable Kaniko Pod.
      hostAliases:
        - ip: "$REGISTRY_IP"
          hostnames: ["$REGISTRY_HOST"]
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
            # Kaniko may chown copied source paths while evaluating COPY . .;
            # its extracted context therefore must remain writable.
            - {name: workspace, mountPath: /workspace}
            - {name: registry-auth, mountPath: /kaniko/.docker, readOnly: true}
      volumes:
        - {name: archive, configMap: {name: $job}}
        - {name: workspace, emptyDir: {}}
        - name: registry-auth
          secret: {secretName: $REGISTRY_SECRET, items: [{key: .dockerconfigjson, path: config.json}]}
EOF
  deadline=$((SECONDS + 1800))
  until [[ $(kubectl get job -n "$NAMESPACE" "$job" -o jsonpath='{.status.succeeded}' 2>/dev/null) == 1 ]]; do
    [[ $(kubectl get job -n "$NAMESPACE" "$job" -o jsonpath='{.status.failed}' 2>/dev/null) != 1 ]] || {
      kubectl logs -n "$NAMESPACE" "job/$job" --tail=200 >&2 || true
      echo "$job failed" >&2
      exit 1
    }
    (( SECONDS < deadline )) || { echo "$job timed out" >&2; exit 1; }
    sleep 5
  done
  digest=$(kubectl get pod -n "$NAMESPACE" -l "job-name=$job" -o jsonpath='{.items[0].status.containerStatuses[0].state.terminated.message}')
  [[ "$digest" == sha256:* ]] || { echo "$name did not emit a digest: $digest" >&2; exit 1; }
  printf '%s=%s@%s\n' "${name//-/_}" "$image" "$digest" | tee -a "$RESULT_FILE"
}

simple_context() {
  local component=$1 image_name=${2:-$1} context
  context="$WORK_DIR/$component"
  mkdir -p "$context"
  cp -a "$REPO_ROOT/images/$component/." "$context/"
  build_context "$component" "$context" "$REGISTRY/$image_name:source-$BUILD_ID"
}

build_horizon_complete() {
  local repo horizon_context
  for repo in "$VPC_DASHBOARD_REPO" "$TELEMETRY_DASHBOARD_REPO" "$S3_DASHBOARD_REPO"; do
    git -C "$repo" diff --quiet && git -C "$repo" diff --cached --quiet || {
      echo "refusing to build from dirty source repository: $repo" >&2
      exit 1
    }
  done
  (cd "$VPC_DASHBOARD_REPO" && "$PYTHON_BINARY" -m build && make verify-wheel)
  (cd "$TELEMETRY_DASHBOARD_REPO" && rm -rf build dist *.egg-info && "$PYTHON_BINARY" -m build)
  (cd "$S3_DASHBOARD_REPO" && rm -rf build dist *.egg-info && "$PYTHON_BINARY" -m build)
  horizon_context="$WORK_DIR/horizon-complete"
  mkdir -p "$horizon_context/octavia-workflow" "$horizon_context/project-selfservice" "$horizon_context/magnum-ui" "$horizon_context/enabled" "$horizon_context/settings" "$horizon_context/service_catalog" "$horizon_context/image_catalog" "$horizon_context/track-b"
  cp "$REPO_ROOT/images/horizon-complete/Dockerfile" "$horizon_context/Dockerfile"
  cp "$REPO_ROOT/images/horizon-complete/enhance_images_ui.py" "$horizon_context/enhance_images_ui.py"
  cp "$REPO_ROOT/images/horizon-complete/image_catalog/index_split.html" "$horizon_context/image_catalog/index_split.html"
  cp "$REPO_ROOT/images/horizon-complete/platform_navigation.py" "$horizon_context/platform_navigation.py"
  cp "$REPO_ROOT/images/horizon-complete/region_selector.html" "$horizon_context/region_selector.html"
  cp "$REPO_ROOT/images/horizon-complete/enabled/_9999_platform_navigation.py" "$horizon_context/enabled/_9999_platform_navigation.py"
  cp "$REPO_ROOT/images/horizon-complete/enabled/_1380_dcn_service_catalog.py" "$horizon_context/enabled/_1380_dcn_service_catalog.py"
  cp -a "$REPO_ROOT/images/horizon-complete/service_catalog/." "$horizon_context/service_catalog/"
  cp "$REPO_ROOT/deploy/config/tenant-service-catalog.yaml" "$horizon_context/tenant-service-catalog.yaml"
  cp "$REPO_ROOT/images/horizon-complete/settings/0001_production_region.py" "$horizon_context/settings/0001_production_region.py"
  cp "$VPC_DASHBOARD_REPO"/dist/openstack_vpc_dashboard-*.whl "$horizon_context/openstack_vpc_dashboard.whl"
  cp "$TELEMETRY_DASHBOARD_REPO"/dist/openstack_telemetry_dashboard-*.whl "$horizon_context/openstack_telemetry_dashboard.whl"
  cp "$S3_DASHBOARD_REPO"/dist/openstack_s3_dashboard-*.whl "$horizon_context/openstack_s3_dashboard.whl"
  cp "$REPO_ROOT/images/horizon-octavia-dashboard"/{model.service.js,loadbalancer.html,loadbalancer.controller.js,listener.html,listener.controller.js,pool.html,pool.controller.js} "$horizon_context/octavia-workflow/"
  cp -a "$REPO_ROOT/images/horizon-project-selfservice-dashboard/pkg/." "$horizon_context/project-selfservice/"
  cp "$REPO_ROOT/images/horizon-magnum-dashboard/enhance_magnum_ui.py" "$horizon_context/magnum-ui/"
  cp -a "$REPO_ROOT/images/horizon-magnum-dashboard/overlay" "$horizon_context/magnum-ui/overlay"
  cp -a "$REPO_ROOT/images/horizon-governance-dashboard/governance_dashboard" "$horizon_context/track-b/"
  build_context horizon-complete "$horizon_context" "$REGISTRY/horizon:source-$BUILD_ID"
}

# Images whose parents are all public and digest-pinned.
for component in gnocchi ceilometer aodh keycloak; do
  selected "$component" && simple_context "$component"
done
selected keystone-oidc && simple_context keystone-oidc keystone
selected neutron-fwaas && simple_context neutron-fwaas neutron
selected octavia-ovn && simple_context octavia-ovn octavia
selected horizon-complete && build_horizon_complete
selected project-facade && simple_context project-facade

build_loki_tenant_gateway() {
  local context="$WORK_DIR/loki-tenant-gateway"
  mkdir -p "$context"
  cp -a "$REPO_ROOT/services/loki-tenant-gateway/." "$context/"
  build_context loki-tenant-gateway "$context" "$REGISTRY/loki-tenant-gateway:source-$BUILD_ID"
}
selected loki-tenant-gateway && build_loki_tenant_gateway

build_nova_extended_compute() {
  local context="$WORK_DIR/nova-extended-compute-source"
  git -C "$NOVA_EXTENDED_COMPUTE_REPO" diff --quiet &&
    git -C "$NOVA_EXTENDED_COMPUTE_REPO" diff --cached --quiet || {
      echo "refusing to build dirty Nova source: $NOVA_EXTENDED_COMPUTE_REPO" >&2
      exit 1
    }
  mkdir -p "$context"
  git -C "$NOVA_EXTENDED_COMPUTE_REPO" archive HEAD | tar -x -C "$context"
  cp "$REPO_ROOT/images/nova-extended-compute/Dockerfile" \
    "$REPO_ROOT/images/nova-extended-compute/verify_installed.py" "$context/"
  build_context nova-extended-compute "$context" "$REGISTRY/nova-extended-compute:source-$BUILD_ID"
}
selected nova-extended-compute && build_nova_extended_compute

build_git_dockerfile() {
  local component=$1 repository=$2 subdirectory=$3 image_name=$4 context="$WORK_DIR/$component-source"
  git -C "$repository" diff --quiet && git -C "$repository" diff --cached --quiet || {
    echo "refusing to build $component from dirty source: $repository" >&2
    exit 1
  }
  mkdir -p "$context"
  git -C "$repository" archive HEAD | tar -x -C "$context"
  if [[ -n "$subdirectory" ]]; then
    context="$context/$subdirectory"
  fi
  build_context "$component" "$context" "$REGISTRY/$image_name:source-$BUILD_ID"
}

selected flyt-adapter && build_git_dockerfile flyt-adapter "$FLYT_ADAPTER_REPO" "" flyt-adapter
selected flyt-cluster-manager && build_git_dockerfile flyt-cluster-manager "$FLYT_MANAGED_RUNTIME_REPO" control-managers flyt-cluster-manager

build_vpc_git_component() {
  local name=$1 dockerfile=$2 tag=$3 context
  git -C "$VPC_CONTROL_PLANE_REPO" diff --quiet && git -C "$VPC_CONTROL_PLANE_REPO" diff --cached --quiet || {
    echo "refusing to build $name from dirty VPC source; git archive HEAD would omit working-tree changes: $VPC_CONTROL_PLANE_REPO" >&2
    exit 1
  }
  context="$WORK_DIR/$name-source"
  mkdir -p "$context"
  git -C "$VPC_CONTROL_PLANE_REPO" archive HEAD | tar -x -C "$context"
  if [[ "$dockerfile" != Dockerfile ]]; then
    cp "$context/$dockerfile" "$context/Dockerfile"
  fi
  build_context "$name" "$context" "$REGISTRY/project-facade:$tag-$BUILD_ID"
}
if [[ -n "$BUILD_COMPONENTS" ]]; then
  selected vpc-control-plane && build_vpc_git_component vpc-control-plane Dockerfile vpc-controller
  selected vpc-facade && build_vpc_git_component vpc-facade Dockerfile.apiserver vpc-facade
  selected vpc-metadata-attestor && build_vpc_git_component vpc-metadata-attestor Dockerfile.metadata-attestor vpc-metadata-attestor
  selected vpc-endpoint-agent && build_vpc_git_component vpc-endpoint-agent Dockerfile.endpoint-agent vpc-endpoint-agent
fi

# Magnum's GitOps-enabled image is layered on the locally rebuilt Magnum base.
# Keep both components available to narrow rebuilds so a missing registry
# digest does not force rebuilding every unrelated platform image.
if selected magnum-capi || selected magnum-capi-gitops || selected magnum-capi-repository-writer; then
  git -C "$MAGNUM_GITOPS_REPO" diff --quiet &&
    git -C "$MAGNUM_GITOPS_REPO" diff --cached --quiet || {
      echo "refusing to build from dirty source repository: $MAGNUM_GITOPS_REPO" >&2
      exit 1
    }
fi
if selected magnum-capi || selected magnum-capi-gitops; then
  simple_context magnum-capi magnum
  magnum_ref=$(awk -F= '$1=="magnum_capi"{print $2}' "$RESULT_FILE")
fi

build_magnum_repository_writer() {
  local writer_context="$WORK_DIR/magnum-capi-repository-writer"
  mkdir -p "$writer_context"
  cp "$REPO_ROOT/images/magnum-capi-gitops/repository-writer.Dockerfile" "$writer_context/Dockerfile"
  cp -a "$MAGNUM_GITOPS_REPO/magnum-driver" "$writer_context/magnum-driver"
  cp -a "$MAGNUM_GITOPS_REPO/repository-writer" "$writer_context/repository-writer"
  mkdir -p "$writer_context/vendor/capi-helm-charts"
  cp -a "$MAGNUM_GITOPS_REPO/vendor/capi-helm-charts/openstack-cluster" "$writer_context/vendor/capi-helm-charts/openstack-cluster"
  build_context magnum-capi-repository-writer "$writer_context" "$REGISTRY/magnum-capi-repository-writer:source-$BUILD_ID"
}
selected magnum-capi-repository-writer && build_magnum_repository_writer
if selected magnum-capi-gitops; then
  magnum_context="$WORK_DIR/magnum-capi-gitops"
  mkdir -p "$magnum_context"
  cp "$REPO_ROOT/images/magnum-capi-gitops/Dockerfile" "$magnum_context/Dockerfile"
  sed -i "s#registry.dcn.ssu.ac.kr/openstack/magnum@sha256:[a-f0-9]*#$magnum_ref#" "$magnum_context/Dockerfile"
  cp -a "$MAGNUM_GITOPS_REPO/magnum-driver" "$magnum_context/magnum-driver"
  build_context magnum-capi-gitops "$magnum_context" "$REGISTRY/magnum-capi-gitops:source-$BUILD_ID"
fi

if [[ -n "$BUILD_COMPONENTS" ]]; then
  echo "Selected source builds completed. Immutable references: $RESULT_FILE"
  exit 0
fi

# Build the VPC binaries from the locked Git checkout, then package only the
# binaries in digest-pinned runtime images.
(cd "$VPC_CONTROL_PLANE_REPO" && CGO_ENABLED=0 GOOS=linux go build -trimpath -o "$WORK_DIR/manager" ./cmd/main.go)
(cd "$VPC_CONTROL_PLANE_REPO" && CGO_ENABLED=0 GOOS=linux go build -trimpath -o "$WORK_DIR/apiserver" ./cmd/apiserver)
(cd "$VPC_CONTROL_PLANE_REPO" && CGO_ENABLED=0 GOOS=linux go build -trimpath -o "$WORK_DIR/metadata-attestor" ./cmd/metadata-attestor)
(cd "$VPC_CONTROL_PLANE_REPO" && CGO_ENABLED=0 GOOS=linux go build -trimpath -o "$WORK_DIR/endpoint-agent" ./cmd/endpoint-agent)
for item in manager:vpc-control-plane:manager-runtime apiserver:vpc-facade:apiserver-runtime metadata-attestor:vpc-metadata-attestor:metadata-attestor-runtime endpoint-agent:vpc-endpoint-agent:endpoint-agent-runtime; do
  IFS=: read -r binary image runtime <<<"$item"
  context="$WORK_DIR/$image"; mkdir -p "$context/dist"
  cp "$WORK_DIR/$binary" "$context/dist/$binary"
  cp "$VPC_CONTROL_PLANE_REPO/Dockerfile.$runtime" "$context/Dockerfile"
  build_context "$image" "$context" "$REGISTRY/$image:source-$BUILD_ID"
done

# One upstream-rooted Horizon image replaces the historical private-image
# layer chain. The wheel is rebuilt from the locked dashboard checkouts.
build_horizon_complete

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
