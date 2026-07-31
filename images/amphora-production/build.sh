#!/usr/bin/env bash
set -euo pipefail

OCTAVIA_COMMIT=50316329bea5ca55b3db9841bf2f804b97247872
DIB_COMMIT=aff6751d052a08a2ee084195e7024f8c5d282a42
REQUIREMENTS_COMMIT=06cd4e8523cbade25fb93efc4f8ea77d6d97064f
CONSTRAINTS_SHA256=04a324d166aa983f79341fe0584e0dc0b1b81377403dc85e47605c43d58db167

BUILD_ROOT=${AMPHORA_BUILD_ROOT:-/home/ubuntu/.cache/octavia-amphora-2026.1}
OUTPUT_DIR=${AMPHORA_OUTPUT_DIR:-/home/ubuntu/amphora-build-output}
OUTPUT_NAME=${AMPHORA_OUTPUT_NAME:-amphora-x64-haproxy-ubuntu-noble-2026.1}

mkdir -p "${BUILD_ROOT}" "${OUTPUT_DIR}"

clone_at_commit() {
  local url=$1
  local commit=$2
  local destination=$3
  if [[ ! -d "${destination}/.git" ]]; then
    git clone --no-checkout "${url}" "${destination}"
  elif [[ "$(git -C "${destination}" rev-parse --is-shallow-repository)" == true ]]; then
    git -C "${destination}" fetch --unshallow --no-filter origin
    git -C "${destination}" config --unset-all remote.origin.promisor || true
    git -C "${destination}" config --unset-all remote.origin.partialclonefilter || true
  fi
  git -C "${destination}" fetch --depth=1 origin "${commit}"
  git -C "${destination}" checkout --detach "${commit}"
  test "$(git -C "${destination}" rev-parse HEAD)" = "${commit}"
  git -C "${destination}" fsck --full
}

clone_at_commit \
  https://opendev.org/openstack/octavia.git \
  "${OCTAVIA_COMMIT}" \
  "${BUILD_ROOT}/octavia"
clone_at_commit \
  https://opendev.org/openstack/diskimage-builder.git \
  "${DIB_COMMIT}" \
  "${BUILD_ROOT}/diskimage-builder"

constraints="${BUILD_ROOT}/upper-constraints.txt"
curl -fsSL \
  "https://opendev.org/openstack/requirements/raw/commit/${REQUIREMENTS_COMMIT}/upper-constraints.txt" \
  -o "${constraints}"
test "$(sha256sum "${constraints}" | awk '{print $1}')" = \
  "${CONSTRAINTS_SHA256}"

python3 -m venv "${BUILD_ROOT}/venv"
"${BUILD_ROOT}/venv/bin/pip" install --upgrade pip
"${BUILD_ROOT}/venv/bin/pip" install \
  --constraint "${constraints}" \
  diskimage-builder==3.40.2

export PATH="${BUILD_ROOT}/venv/bin:${PATH}"
export DIB_REPO_PATH="${BUILD_ROOT}/diskimage-builder"
export DIB_REPOLOCATION_amphora_agent="${BUILD_ROOT}/octavia"
export DIB_REPOREF_amphora_agent="${OCTAVIA_COMMIT}"
export DIB_REPOLOCATION_upper_constraints="file://${constraints}"
export CLOUD_INIT_DATASOURCES=ConfigDrive

output="${OUTPUT_DIR}/${OUTPUT_NAME}.qcow2"
log="${OUTPUT_DIR}/${OUTPUT_NAME}.build.log"

"${BUILD_ROOT}/octavia/diskimage-create/diskimage-create.sh" \
  -a amd64 \
  -b haproxy \
  -d noble \
  -i ubuntu-minimal \
  -n \
  -s 2 \
  -t qcow2 \
  -o "${output}" \
  -c "${BUILD_ROOT}/cache" \
  -w "${BUILD_ROOT}/work" \
  -l "${log}"

qemu-img check "${output}"
qemu-img info --output=json "${output}" > \
  "${OUTPUT_DIR}/${OUTPUT_NAME}.qemu-info.json"
sha256sum "${output}" > "${output}.sha256"

printf 'Built %s\n' "${output}"
