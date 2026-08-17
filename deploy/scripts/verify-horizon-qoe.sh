#!/usr/bin/env bash
set -euo pipefail

NAMESPACE=${NAMESPACE:-openstack}
HORIZON_URL=${HORIZON_URL:-https://cloud.dcn.ssu.ac.kr/horizon}
HORIZON_RESOLVE=${HORIZON_RESOLVE:-}
SAMPLES=${SAMPLES:-5}
work_dir=$(mktemp -d /tmp/horizon-qoe.XXXXXX)
cleanup() {
  shred -u "$work_dir"/* 2>/dev/null || true
  rmdir "$work_dir" 2>/dev/null || true
}
trap cleanup EXIT
umask 077

curl_args=(-ksS)
if [[ -n "$HORIZON_RESOLVE" ]]; then
  curl_args+=(--resolve "$HORIZON_RESOLVE")
fi

for command in curl kubectl python3 base64; do
  command -v "$command" >/dev/null || { echo "missing command: $command" >&2; exit 1; }
done

secret=horizon-keystone-admin
secret_value() {
  kubectl get secret -n "$NAMESPACE" "$secret" \
    -o "jsonpath={.data.$1}" | base64 -d
}

cookie="$work_dir/cookies"
login="$work_dir/login.html"
curl "${curl_args[@]}" -c "$cookie" "$HORIZON_URL/auth/login/" -o "$login"
csrf=$(python3 - "$login" <<'PY'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', text)
if not match:
    raise SystemExit("Horizon login form has no CSRF token")
print(match.group(1))
PY
)
region=$(python3 - "$login" <<'PY'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
match = re.search(r'name="region" value="([^"]+)"', text)
print(match.group(1) if match else "default")
PY
)

username=$(secret_value OS_USERNAME)
password=$(secret_value OS_PASSWORD)
domain=$(secret_value OS_USER_DOMAIN_NAME)
status=$(curl "${curl_args[@]}" -b "$cookie" -c "$cookie" -o "$work_dir/auth-response" \
  -w '%{http_code}' -X POST "$HORIZON_URL/auth/login/" \
  --data-urlencode "csrfmiddlewaretoken=$csrf" \
  --data-urlencode auth_type=credentials \
  --data-urlencode "region=$region" \
  --data-urlencode "username=$username" \
  --data-urlencode "password=$password" \
  --data-urlencode "domain=$domain" \
  -e "$HORIZON_URL/auth/login/")
unset username password domain
[[ "$status" == 302 ]] || { echo "Horizon benchmark login failed: HTTP $status" >&2; exit 1; }

affinity=$(kubectl get service -n "$NAMESPACE" horizon-int -o jsonpath='{.spec.sessionAffinity}')
[[ "$affinity" == ClientIP ]] || {
  echo "horizon-int session affinity is $affinity, expected ClientIP" >&2
  exit 1
}

# A 200 response from the stock image table is not sufficient: require the
# customized inspector markup and keep metadata out of the display name.
images_html="$work_dir/images.html"
images_status=$(curl "${curl_args[@]}" -b "$cookie" -o "$images_html" \
  -w '%{http_code}' "$HORIZON_URL/project/images/")
[[ "$images_status" == 200 ]] || {
  echo "images catalogue returned HTTP $images_status" >&2
  exit 1
}
grep -q 'id="image-inspector"' "$images_html" || {
  echo "images catalogue is missing the lower detail inspector" >&2
  exit 1
}
if grep -q '— CAPI Kubernetes' "$images_html"; then
  echo "CAPI metadata leaked into the image display name" >&2
  exit 1
fi
image_id=$(python3 - "$images_html" <<'PY'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
rows = re.findall(r"<tr\b.*?</tr>", text, flags=re.I | re.S)
preferred = next((row for row in rows if "ubuntu-noble-kube" in row), "")
scope = preferred or text
match = re.search(
    r"<input\b(?=[^>]*\bname=[\"']object_ids[\"'])[^>]*\bvalue=[\"']([^\"']+)",
    scope,
    flags=re.I | re.S,
)
if not match:
    raise SystemExit("images catalogue has no selectable image UUID")
print(match.group(1))
PY
)
image_json="$work_dir/image-detail.json"
detail_status=$(curl "${curl_args[@]}" -b "$cookie" -o "$image_json" \
  -w '%{http_code}' "$HORIZON_URL/api/glance/images/$image_id/")
[[ "$detail_status" == 200 ]] || {
  echo "image detail API returned HTTP $detail_status" >&2
  exit 1
}
python3 - "$image_json" "$image_id" <<'PY'
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
assert data.get("id") == sys.argv[2], data
assert data.get("name"), data
properties = data.get("properties") or data
if "kube" in data["name"]:
    assert properties.get("kube_version"), properties
    assert properties.get("dcn_support_status"), properties
PY

# These pages exercise Nova, Glance, Cinder, Designate, the VPC facade, and
# Horizon's common project overview. Budgets are medians, so a rolling restart
# or one transient control-plane request does not create a false regression.
pages=(
  "overview|project/|5.0"
  "instances|project/instances/|5.0"
  "images|project/images/|4.0"
  "volumes|project/volumes/|7.0"
  "dns-zones|project/dnszones/|4.0"
  "clusters|project/clusters/|4.0"
  "telemetry|project/cloud_metrics/|4.0"
  "object-storage|project/cloud_s3/|4.0"
  "vpc-list|project/vpcs/|7.0"
  "vpc-topology|project/vpc_topology/|5.0"
  "instance-launch|project/instances/launch-instance/|7.0"
)

failed=0
for entry in "${pages[@]}"; do
  IFS='|' read -r name path budget <<<"$entry"
  samples=()
  for ((i=0; i<SAMPLES; i++)); do
    result=$(curl "${curl_args[@]}" -b "$cookie" -o /dev/null \
      -w '%{http_code} %{time_starttransfer}' "$HORIZON_URL/$path")
    read -r code elapsed <<<"$result"
    [[ "$code" == 200 ]] || { echo "$name returned HTTP $code" >&2; failed=1; continue; }
    samples+=("$elapsed")
  done
  [[ "${#samples[@]}" -eq "$SAMPLES" ]] || continue
  median=$(printf '%s\n' "${samples[@]}" | sort -n | sed -n "$((SAMPLES / 2 + 1))p")
  maximum=$(printf '%s\n' "${samples[@]}" | sort -n | tail -1)
  if python3 - "$median" "$budget" <<'PY'
import sys
raise SystemExit(0 if float(sys.argv[1]) < float(sys.argv[2]) else 1)
PY
  then
    printf '%-16s median TTFB %6.3fs, max %6.3fs (budget <%ss)\n' "$name" "$median" "$maximum" "$budget"
  else
    printf '%-16s median TTFB %6.3fs exceeds %ss\n' "$name" "$median" "$budget" >&2
    failed=1
  fi
done

exit "$failed"
