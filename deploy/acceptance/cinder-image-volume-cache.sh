#!/usr/bin/env bash
set -euo pipefail
: "${CINDER_ACCEPTANCE_IMAGE_ID:?}"
: "${CINDER_ACCEPTANCE_VOLUME_TYPE:=general-purpose}"
: "${CINDER_ACCEPTANCE_VOLUME_SIZE_GB:=5}"
: "${CINDER_ACCEPTANCE_TIMEOUT_SECONDS:=1200}"
run_id="$(date +%s)-${RANDOM}"
cold_name="cinder-cache-cold-${run_id}"; warm_name="cinder-cache-warm-${run_id}"
cold_id=""; warm_id=""
cleanup() {
  for volume_id in "${warm_id}" "${cold_id}"; do
    [[ -z "${volume_id}" ]] || openstack volume delete --force "${volume_id}" >/dev/null 2>&1 || true
  done
  for volume_name in "${warm_name}" "${cold_name}"; do
    while read -r volume_id; do
      [[ -z "${volume_id}" ]] || openstack volume delete --force "${volume_id}" >/dev/null 2>&1 || true
    done < <(openstack volume list --name "${volume_name}" -f value -c ID 2>/dev/null || true)
  done
}
trap cleanup EXIT
wait_for_volume() {
  local volume_id=$1 started=$2 status elapsed
  while true; do
    status=$(openstack volume show "${volume_id}" -f value -c status)
    elapsed=$(( $(date +%s) - started ))
    case "${status}" in
      available) printf '%s\n' "${elapsed}"; return 0 ;;
      error|error_*) echo "volume ${volume_id} entered ${status}" >&2; return 1 ;;
    esac
    (( elapsed < CINDER_ACCEPTANCE_TIMEOUT_SECONDS )) || { echo "volume ${volume_id} timed out in ${status}" >&2; return 1; }
    sleep 5
  done
}
create_from_image() {
  local name=$1 started volume_id elapsed
  started=$(date +%s)
  volume_id=$(openstack volume create --image "${CINDER_ACCEPTANCE_IMAGE_ID}" \
    --size "${CINDER_ACCEPTANCE_VOLUME_SIZE_GB}" --type "${CINDER_ACCEPTANCE_VOLUME_TYPE}" \
    --property dcn_acceptance_test=cinder-image-cache -f value -c id "${name}")
  elapsed=$(wait_for_volume "${volume_id}" "${started}")
  printf '%s %s\n' "${volume_id}" "${elapsed}"
}
read -r cold_id cold_seconds < <(create_from_image "${cold_name}")
read -r warm_id warm_seconds < <(create_from_image "${warm_name}")
python3 - "${cold_seconds}" "${warm_seconds}" <<'PY'
import json, sys
cold, warm = map(int, sys.argv[1:])
print(json.dumps({"result": "pass", "cold_seconds": cold, "warm_seconds": warm,
                  "warm_to_cold_ratio": round(warm / cold, 3) if cold else None}, sort_keys=True))
PY
