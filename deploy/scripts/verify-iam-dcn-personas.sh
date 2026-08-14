#!/usr/bin/env bash
set -euo pipefail

# Positive/negative access verification for the six project-scoped dcn-domain personas
# reconciled by reconcile-iam-dcn.sh (see PERSONA_ROLES there and
# openstack-cloud-services/docs/proposals/iam-hardening/README.md,
# "Persona positive/negative access matrix"). For each persona: create a
# disposable local Keystone user, add to the matching group, confirm real
# effective (group-inherited) roles, issue a real password-scoped token,
# and assert the expected outcome of three real API calls. Every test user
# is deleted immediately after, on both success and failure (trap).
#
# Expected result matrix (see the README section above for why -- e.g.
# load balancer listing only needs project membership, not
# load-balancer_admin, per Octavia's actual default policy. The site's
# explicit Keystone policy grants identity inventory reads to `monitoring`,
# so operators intentionally pass the known-user visibility check):
#   openstack-admins:    network_list OK, loadbalancer_list OK, user_list OK
#   openstack-operators: network_list OK, loadbalancer_list OK, user_show OK
#   openstack-members:   network_list OK, loadbalancer_list OK, user_list DENIED
#   openstack-readers:   network_list OK, loadbalancer_list OK, user_list DENIED
#
# Requires: kubectl access to the `openstack` namespace and permission to
# create/exec/delete a pod there (uses a throwaway openstack-client pod,
# matching persona-authz-test from the original manual run). Run from a
# cluster node.

NAMESPACE=openstack
POD=iam-persona-verify
DOMAIN=dcn
PROJECT=dcn

cat > /tmp/iam-persona-verify-pod.$$.yaml <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: ${POD}
  namespace: ${NAMESPACE}
spec:
  restartPolicy: Never
  containers:
    - name: osc
      image: quay.io/airshipit/openstack-client:2026.1-ubuntu_noble
      command: ["sleep", "1800"]
      envFrom:
        - secretRef:
            name: keystone-keystone-admin
EOF
BINDING_WAS_PRESENT=1
PROJECT_NAMESPACE=
cleanup() {
  kubectl -n "${NAMESPACE}" delete pod "${POD}" --ignore-not-found --wait=false >/dev/null
  rm -f /tmp/iam-persona-verify-pod.$$.yaml
  if [[ "$BINDING_WAS_PRESENT" == 0 && "$PROJECT_NAMESPACE" == vpc-* ]]; then
    kubectl -n "$PROJECT_NAMESPACE" delete secret openstack-credentials --ignore-not-found >/dev/null
  fi
}
trap cleanup EXIT

kubectl -n "${NAMESPACE}" delete pod "${POD}" --ignore-not-found --wait=true
kubectl apply -f "/tmp/iam-persona-verify-pod.$$.yaml"
kubectl -n "${NAMESPACE}" wait --for=condition=Ready "pod/${POD}" --timeout=60s
# Pod Ready can precede Cilium DNS/service dataplane readiness by a few
# seconds on a freshly attached endpoint. Do not misreport that transient as
# an IAM denial; wait until both cluster and public API names are usable.
for _ in $(seq 1 30); do
  if kubectl -n "${NAMESPACE}" exec "${POD}" -- sh -c \
    'getent hosts keystone-api.openstack.svc.cluster.local >/dev/null &&
     getent hosts cloud.dcn.ssu.ac.kr >/dev/null &&
     curl -ksS --connect-timeout 3 --max-time 5 -o /dev/null https://cloud.dcn.ssu.ac.kr/' \
    >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
kubectl -n "${NAMESPACE}" exec "${POD}" -- \
  getent hosts cloud.dcn.ssu.ac.kr >/dev/null
project_id=$(kubectl -n "${NAMESPACE}" exec "${POD}" -- \
  openstack project show --domain "$DOMAIN" "$PROJECT" -f value -c id)
PROJECT_NAMESPACE="vpc-${project_id}"
if ! kubectl -n "$PROJECT_NAMESPACE" get secret openstack-credentials >/dev/null 2>&1; then
  BINDING_WAS_PRESENT=0
fi

cat > /tmp/iam-persona-verify-script.$$.sh <<'INNER'
#!/bin/sh
set -e
DOMAIN=dcn
PROJECT=dcn
fail=0

# Keystone region objects cannot be disabled, so the acceptance contract is:
# the production region has enabled endpoints and both historical regions have
# none. This also guarantees Horizon cannot offer a stale region selector.
enabled_endpoint_count() {
  openstack endpoint list --region "$1" -f json |
    python3 -c 'import json,sys; print(sum(str(x["Enabled"]).lower() == "true" for x in json.load(sys.stdin)))'
}
test "$(enabled_endpoint_count seoul-ssu-1)" -gt 0
test "$(enabled_endpoint_count RegionOne)" -eq 0
test "$(enabled_endpoint_count RegionOne-VM)" -eq 0
echo "PASS: seoul-ssu-1 is the only enabled Keystone endpoint region"

# Remove legacy fixed-name users left by an interrupted pre-2026-08-01 run.
# Current runs use unique names and only delete their own user IDs.
for legacy_persona in admins operators members readers network-operators security-operators; do
  openstack user delete "verify-openstack-${legacy_persona}" 2>/dev/null || true
done

# args: persona expect_networks expect_lbs expect_users expect_vpc_write
#       expect_network_sharing expect_security_policy (OK|DENIED each)
check_persona() {
  persona="$1"; expect_net="$2"; expect_lb="$3"; expect_users="$4"
  expect_vpc="$5"; expect_sharing="$6"; expect_security="$7"
  echo "== persona: $persona (expect network=$expect_net lb=$expect_lb users=$expect_users) =="
  user="verify-${persona}-$(date +%s)-$$"
  pass="VerifyPass!$(date +%s)$$"

  uid=$(openstack user create --domain "$DOMAIN" --password "$pass" "$user" -f value -c id)
  trap "openstack user delete '$uid' 2>/dev/null || true" EXIT
  openstack group add user --group-domain "$DOMAIN" --user-domain "$DOMAIN" "$persona" "$user"

  echo "-- effective roles --"
  openstack role assignment list --user "$uid" --project "$PROJECT" --project-domain "$DOMAIN" --effective --names -f value -c Role

  token=$(openstack --os-username "$user" --os-password "$pass" \
    --os-user-domain-name "$DOMAIN" --os-project-name "$PROJECT" \
    --os-project-domain-name "$DOMAIN" --os-auth-type password \
    token issue -f value -c id)

  compute_url=$(openstack endpoint list --service compute --interface public \
    --region seoul-ssu-1 -f value -c URL | head -1)
  for path in '/limits?reserved=1' '/os-availability-zone'; do
    code=$(curl -ksS --retry 3 --retry-all-errors --retry-delay 1 \
      --connect-timeout 5 --max-time 15 -o /tmp/nova_verify_out.$$ \
      -w '%{http_code}' -H "X-Auth-Token: $token" "${compute_url%/}${path}")
    if [ "$code" = 200 ]; then
      echo "PASS: nova $path -> HTTP 200"
    else
      echo "FAIL: nova $path -> HTTP $code, expected 200"
      cat /tmp/nova_verify_out.$$ 2>/dev/null || true
      fail=1
    fi
    rm -f /tmp/nova_verify_out.$$
  done

  # Query a known administrator rather than merely executing `user list`:
  # Keystone may legally return a filtered/self-only list with exit status 0.
  for check in "network list:net:$expect_net" "loadbalancer list:lb:$expect_lb" "user show --domain $OS_USER_DOMAIN_NAME $OS_USERNAME:users:$expect_users"; do
    cmd="${check%%:*}"; rest="${check#*:}"; label="${rest%%:*}"; expect="${rest#*:}"
    if env -u OS_USERNAME -u OS_PASSWORD -u OS_USER_DOMAIN_NAME -u OS_PROJECT_NAME -u OS_PROJECT_DOMAIN_NAME \
      openstack --os-token "$token" --os-auth-type token --os-auth-url "$OS_AUTH_URL" \
      --os-project-name "$PROJECT" --os-project-domain-name "$DOMAIN" \
      $cmd -f value -c ID >/tmp/verify_out.$$ 2>/tmp/verify_err.$$; then
      actual=OK
    else
      actual=DENIED
    fi
    if [ "$actual" = "$expect" ]; then
      echo "PASS: $label -> $actual (expected)"
    else
      echo "FAIL: $label -> $actual, expected $expect"
      tail -3 /tmp/verify_err.$$ 2>/dev/null || true
      fail=1
    fi
    rm -f /tmp/verify_out.$$ /tmp/verify_err.$$
  done

  # These deliberately malformed, empty write requests cannot create a
  # resource. HTTP 403 means the facade authorization layer denied the
  # persona; any other response means authorization succeeded and request
  # validation (normally HTTP 400) was reached.
  for check in \
    "vpc-write:/v1/vpcs:$expect_vpc" \
    "network-sharing:/v1/vpc-peerings:$expect_sharing" \
    "security-policy:/v1/flow-logs:$expect_security"; do
    label="${check%%:*}"; rest="${check#*:}"; path="${rest%%:*}"; expect="${rest#*:}"
    code=$(curl -ksS --retry 3 --retry-all-errors --retry-delay 1 \
      --connect-timeout 5 --max-time 15 -o /tmp/vpc_verify_out.$$ -w '%{http_code}' -X POST \
      -H "X-Auth-Token: $token" -H 'Content-Type: application/json' \
      -d '{}' "https://cloud.dcn.ssu.ac.kr/vpc-api${path}")
    if [ "$code" = 403 ]; then
      actual=DENIED
    elif [ "$code" = 000 ] || [ "$code" = 401 ] || [ "$code" -ge 500 ]; then
      echo "FAIL: $label facade authentication/availability failure (HTTP $code)"
      cat /tmp/vpc_verify_out.$$ 2>/dev/null || true
      fail=1
      rm -f /tmp/vpc_verify_out.$$
      continue
    else
      actual=OK
    fi
    if [ "$actual" = "$expect" ]; then
      echo "PASS: $label -> $actual (HTTP $code)"
    else
      echo "FAIL: $label -> $actual (HTTP $code), expected $expect"
      cat /tmp/vpc_verify_out.$$ 2>/dev/null || true
      fail=1
    fi
    rm -f /tmp/vpc_verify_out.$$
  done

  openstack user delete "$uid"
  trap - EXIT
  echo
}

check_persona openstack-admins             OK OK OK     OK OK     OK
check_persona openstack-operators          OK OK OK     OK DENIED DENIED
check_persona openstack-members            OK OK DENIED OK DENIED DENIED
check_persona openstack-readers            OK OK DENIED DENIED DENIED DENIED
check_persona openstack-network-operators  OK OK DENIED OK OK     DENIED
check_persona openstack-security-operators OK OK DENIED OK DENIED OK

exit "$fail"
INNER

kubectl -n "${NAMESPACE}" cp "/tmp/iam-persona-verify-script.$$.sh" "${NAMESPACE}/${POD}:/tmp/verify.sh"
rm -f "/tmp/iam-persona-verify-script.$$.sh"
kubectl -n "${NAMESPACE}" exec "${POD}" -- sh /tmp/verify.sh
echo "== all persona access checks matched the expected matrix =="
