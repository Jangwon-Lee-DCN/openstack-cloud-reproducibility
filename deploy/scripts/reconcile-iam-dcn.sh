#!/usr/bin/env bash
set -euo pipefail

# Idempotent reconciler for the dcn-domain federated RBAC design described
# in openstack-cloud-services/docs/proposals/iam-hardening/README.md
# ("Path A" -- Keycloak group membership drives Keystone group/role
# assignment via the keycloak-dcn federation mapping). Safe to re-run: every
# object is checked for existence before being created, and the mapping
# PATCH is idempotent by construction (same input always produces the same
# stored rules).
#
# Seven personas as of 2026-08-01, extended from the original four per
# "Coordinated implementation direction for the VPC platform" in the IAM
# hardening doc: admins/operators/members/readers (project-scoped, as
# before) plus domain-admins (domain-scoped -- see DOMAIN_PERSONA_ROLES),
# network-operators and security-operators (project-scoped, carrying new
# custom marker roles that VPC-facade OPA policy is meant to consult --
# see that doc section for what each should authorize; Keystone itself
# enforces nothing extra for them). cloud-admin (system-scope) is
# deliberately not implemented here -- see the same doc section for why.
#
# Requires: kubectl access to both the `keycloak` and `openstack` namespaces,
# and direct network reachability to their ClusterIP Services (this script
# is written to run from a cluster node, matching reconcile-octavia.sh).

KEYCLOAK_HOST=keycloak-service.keycloak.svc.cluster.local
KEYSTONE_HOST=keystone-api.openstack.svc.cluster.local
KEYCLOAK_SVC="${KEYCLOAK_HOST}:8080"
REALM=dcn
KEYSTONE_CLIENT_ID=keystone
DOMAIN=dcn
PROJECT=dcn

# This script runs on a cluster node (matching reconcile-octavia.sh), whose
# own resolv.conf does not resolve .svc.cluster.local names -- only pods get
# that via their injected DNS config. Resolve the real ClusterIPs via
# kubectl and force curl to use them with --resolve, so the FQDNs stored in
# secrets/config (which do work correctly from inside any pod) don't need
# to be rewritten here.
KEYCLOAK_IP=$(kubectl -n keycloak get svc keycloak-service -o jsonpath='{.spec.clusterIP}')
KEYSTONE_IP=$(kubectl -n openstack get svc keystone-api -o jsonpath='{.spec.clusterIP}')
CURL_RESOLVE=(--resolve "${KEYCLOAK_HOST}:8080:${KEYCLOAK_IP}" --resolve "${KEYSTONE_HOST}:5000:${KEYSTONE_IP}")
curl() { command curl "${CURL_RESOLVE[@]}" "$@"; }

KC_USER=$(kubectl -n keycloak get secret keycloak-bootstrap-admin -o jsonpath='{.data.username}' | base64 -d)
KC_PASS=$(kubectl -n keycloak get secret keycloak-bootstrap-admin -o jsonpath='{.data.password}' | base64 -d)
OS_AUTH_URL=$(kubectl -n openstack get secret keystone-keystone-admin -o jsonpath='{.data.OS_AUTH_URL}' | base64 -d)
OS_USERNAME=$(kubectl -n openstack get secret keystone-keystone-admin -o jsonpath='{.data.OS_USERNAME}' | base64 -d)
OS_PASSWORD=$(kubectl -n openstack get secret keystone-keystone-admin -o jsonpath='{.data.OS_PASSWORD}' | base64 -d)
OS_USER_DOMAIN_NAME=$(kubectl -n openstack get secret keystone-keystone-admin -o jsonpath='{.data.OS_USER_DOMAIN_NAME}' | base64 -d)
OS_PROJECT_NAME=$(kubectl -n openstack get secret keystone-keystone-admin -o jsonpath='{.data.OS_PROJECT_NAME}' | base64 -d)
OS_PROJECT_DOMAIN_NAME=$(kubectl -n openstack get secret keystone-keystone-admin -o jsonpath='{.data.OS_PROJECT_DOMAIN_NAME}' | base64 -d)

kc_token() {
  curl -sf -X POST "http://${KEYCLOAK_SVC}/realms/master/protocol/openid-connect/token" \
    -d "client_id=admin-cli" -d "username=${KC_USER}" -d "password=${KC_PASS}" \
    -d "grant_type=password" | jq -r .access_token
}

os_token_and_project_id() {
  local body
  body=$(curl -sf -X POST "${OS_AUTH_URL}/auth/tokens" \
    -H 'Content-Type: application/json' -d "{
      \"auth\": {
        \"identity\": {
          \"methods\": [\"password\"],
          \"password\": {
            \"user\": {
              \"name\": \"${OS_USERNAME}\",
              \"domain\": {\"name\": \"${OS_USER_DOMAIN_NAME}\"},
              \"password\": \"${OS_PASSWORD}\"
            }
          }
        },
        \"scope\": {
          \"project\": {
            \"name\": \"${OS_PROJECT_NAME}\",
            \"domain\": {\"name\": \"${OS_PROJECT_DOMAIN_NAME}\"}
          }
        }
      }
    }" -D - -o /tmp/.os_token_body.$$)
  OS_TOKEN=$(printf '%s' "$body" | grep -i '^X-Subject-Token:' | tr -d '\r' | awk '{print $2}')
  rm -f /tmp/.os_token_body.$$
}

echo "== authenticating to Keycloak and Keystone =="
KC_TOKEN=$(kc_token)
os_token_and_project_id
test -n "${KC_TOKEN}"
test -n "${OS_TOKEN}"

echo "== resolving Keystone domain/project ids =="
DOMAIN_ID=$(curl -sf -H "X-Auth-Token: ${OS_TOKEN}" "${OS_AUTH_URL}/domains?name=${DOMAIN}" | jq -r '.domains[0].id')
PROJECT_ID=$(curl -sf -H "X-Auth-Token: ${OS_TOKEN}" "${OS_AUTH_URL}/projects?name=${PROJECT}&domain_id=${DOMAIN_ID}" | jq -r '.projects[0].id')
test -n "${DOMAIN_ID}" && test "${DOMAIN_ID}" != null
test -n "${PROJECT_ID}" && test "${PROJECT_ID}" != null

echo "== resolving Keycloak keystone client internal id =="
KC_CLIENT_UUID=$(curl -sf -H "Authorization: Bearer ${KC_TOKEN}" \
  "http://${KEYCLOAK_SVC}/admin/realms/${REALM}/clients?clientId=${KEYSTONE_CLIENT_ID}" | jq -r '.[0].id')
test -n "${KC_CLIENT_UUID}" && test "${KC_CLIENT_UUID}" != null

echo "== ensuring Keycloak 'groups' claim mapper on the keystone client =="
existing_mapper=$(curl -sf -H "Authorization: Bearer ${KC_TOKEN}" \
  "http://${KEYCLOAK_SVC}/admin/realms/${REALM}/clients/${KC_CLIENT_UUID}/protocol-mappers/models" \
  | jq -r '.[] | select(.name=="groups") | .id')
if [[ -z "${existing_mapper}" ]]; then
  curl -sf -X POST -H "Authorization: Bearer ${KC_TOKEN}" -H 'Content-Type: application/json' \
    -d '{
      "name": "groups",
      "protocol": "openid-connect",
      "protocolMapper": "oidc-group-membership-mapper",
      "consentRequired": false,
      "config": {
        "full.path": "false",
        "id.token.claim": "true",
        "access.token.claim": "true",
        "userinfo.token.claim": "true",
        "claim.name": "groups"
      }
    }' "http://${KEYCLOAK_SVC}/admin/realms/${REALM}/clients/${KC_CLIENT_UUID}/protocol-mappers/models"
  echo "created groups mapper"
else
  echo "groups mapper already present (${existing_mapper})"
fi

# Custom roles this design needs that don't ship with OpenStack by default.
# These are markers consulted by VPC-facade OPA policy (Path B), not
# Keystone policy.yaml overrides -- see "Coordinated implementation
# direction for the VPC platform" in the IAM hardening doc for what each
# is meant to authorize (Peering/TGW for network-operator; SG/NACL/Flow Log
# for security-operator). Ensuring they exist here only makes them
# assignable; it grants no OpenStack-service-level capability by itself.
echo "== ensuring custom roles exist =="
for role_name in network-operator security-operator; do
  existing=$(curl -sf -H "X-Auth-Token: ${OS_TOKEN}" "${OS_AUTH_URL}/roles?name=${role_name}" | jq -r '.roles[0].id // empty')
  if [[ -z "${existing}" ]]; then
    curl -sf -X POST -H "X-Auth-Token: ${OS_TOKEN}" -H 'Content-Type: application/json' \
      -d "{\"role\": {\"name\": \"${role_name}\"}}" "${OS_AUTH_URL}/roles" >/dev/null
    echo "created role ${role_name}"
  else
    echo "role ${role_name} already present (${existing})"
  fi
done

# persona -> Keystone role list on ${PROJECT} (project-scoped personas only;
# domain-admins is handled separately below since it needs a domain-scoped
# assignment, not a project-scoped one). cloud-admin (system-scope) is
# deliberately not implemented here -- see "Coordinated implementation
# direction for the VPC platform" in the IAM hardening doc: granting
# system-scope through federation needs its own design pass weighed against
# the existing local break-glass admin model, not a default extension of
# this pattern.
declare -A PERSONA_ROLES=(
  [openstack-admins]="admin"
  [openstack-operators]="member load-balancer_admin monitoring"
  [openstack-members]="member"
  [openstack-readers]="reader"
  [openstack-network-operators]="member network-operator"
  [openstack-security-operators]="member security-operator"
)

# domain-admins gets a domain-scoped role assignment (below), not a
# project-scoped one from PERSONA_ROLES -- handled as its own array so the
# generic project-scoped loop doesn't need a special case.
declare -A DOMAIN_PERSONA_ROLES=(
  [openstack-domain-admins]="admin"
)

echo "== ensuring Keycloak groups =="
for persona in "${!PERSONA_ROLES[@]}" "${!DOMAIN_PERSONA_ROLES[@]}"; do
  existing=$(curl -sf -H "Authorization: Bearer ${KC_TOKEN}" \
    "http://${KEYCLOAK_SVC}/admin/realms/${REALM}/groups?search=${persona}&exact=true" | jq -r '.[0].id // empty')
  if [[ -z "${existing}" ]]; then
    curl -sf -X POST -H "Authorization: Bearer ${KC_TOKEN}" -H 'Content-Type: application/json' \
      -d "{\"name\": \"${persona}\"}" "http://${KEYCLOAK_SVC}/admin/realms/${REALM}/groups"
    echo "created Keycloak group ${persona}"
  else
    echo "Keycloak group ${persona} already present"
  fi
done

role_id() {
  curl -sf -H "X-Auth-Token: ${OS_TOKEN}" "${OS_AUTH_URL}/roles?name=$1" | jq -r '.roles[0].id // empty'
}

ensure_keystone_group() {
  local persona="$1" group_id
  group_id=$(curl -sf -H "X-Auth-Token: ${OS_TOKEN}" \
    "${OS_AUTH_URL}/groups?name=${persona}&domain_id=${DOMAIN_ID}" | jq -r '.groups[0].id // empty')
  if [[ -z "${group_id}" ]]; then
    group_id=$(curl -sf -X POST -H "X-Auth-Token: ${OS_TOKEN}" -H 'Content-Type: application/json' \
      -d "{\"group\": {\"name\": \"${persona}\", \"domain_id\": \"${DOMAIN_ID}\"}}" \
      "${OS_AUTH_URL}/groups" | jq -r '.group.id')
    echo "created Keystone group ${persona} (${group_id})" >&2
  else
    echo "Keystone group ${persona} already present (${group_id})" >&2
  fi
  printf '%s' "${group_id}"
}

echo "== ensuring Keystone groups + project-scoped role assignments =="
for persona in "${!PERSONA_ROLES[@]}"; do
  group_id=$(ensure_keystone_group "${persona}")

  for role_name in ${PERSONA_ROLES[$persona]}; do
    rid=$(role_id "${role_name}")
    test -n "${rid}"
    # PUT is idempotent: 204 whether or not the assignment already existed.
    curl -sf -o /dev/null -X PUT -H "X-Auth-Token: ${OS_TOKEN}" \
      "${OS_AUTH_URL}/projects/${PROJECT_ID}/groups/${group_id}/roles/${rid}"
    echo "ensured project-scoped role '${role_name}' on group ${persona}"
  done
done

echo "== ensuring Keystone groups + domain-scoped role assignments =="
for persona in "${!DOMAIN_PERSONA_ROLES[@]}"; do
  group_id=$(ensure_keystone_group "${persona}")

  for role_name in ${DOMAIN_PERSONA_ROLES[$persona]}; do
    rid=$(role_id "${role_name}")
    test -n "${rid}"
    # Domain-scoped assignment (note: /domains/, not /projects/) -- this is
    # what makes openstack-domain-admins "administration limited to one
    # Keystone domain" rather than project-scoped or system-wide.
    curl -sf -o /dev/null -X PUT -H "X-Auth-Token: ${OS_TOKEN}" \
      "${OS_AUTH_URL}/domains/${DOMAIN_ID}/groups/${group_id}/roles/${rid}"
    echo "ensured domain-scoped role '${role_name}' on group ${persona}"
  done
done

echo "== reconciling keycloak-dcn Keystone federation mapping =="
MAPPING_RULES=$(cat <<EOF
[
  {"local": [{"user": {"name": "{0}"}}, {"group": {"name": "openstack-admins", "domain": {"name": "${DOMAIN}"}}}],
   "remote": [{"type": "OIDC-preferred_username"}, {"type": "OIDC-groups", "any_one_of": ["openstack-admins"]}]},
  {"local": [{"user": {"name": "{0}"}}, {"group": {"name": "openstack-operators", "domain": {"name": "${DOMAIN}"}}}],
   "remote": [{"type": "OIDC-preferred_username"}, {"type": "OIDC-groups", "any_one_of": ["openstack-operators"]}]},
  {"local": [{"user": {"name": "{0}"}}, {"group": {"name": "openstack-readers", "domain": {"name": "${DOMAIN}"}}}],
   "remote": [{"type": "OIDC-preferred_username"}, {"type": "OIDC-groups", "any_one_of": ["openstack-readers"]}]},
  {"local": [{"user": {"name": "{0}"}}, {"group": {"name": "openstack-members", "domain": {"name": "${DOMAIN}"}}}],
   "remote": [{"type": "OIDC-preferred_username"}, {"type": "OIDC-groups", "any_one_of": ["openstack-members"]}]},
  {"local": [{"user": {"name": "{0}"}}, {"group": {"name": "openstack-domain-admins", "domain": {"name": "${DOMAIN}"}}}],
   "remote": [{"type": "OIDC-preferred_username"}, {"type": "OIDC-groups", "any_one_of": ["openstack-domain-admins"]}]},
  {"local": [{"user": {"name": "{0}"}}, {"group": {"name": "openstack-network-operators", "domain": {"name": "${DOMAIN}"}}}],
   "remote": [{"type": "OIDC-preferred_username"}, {"type": "OIDC-groups", "any_one_of": ["openstack-network-operators"]}]},
  {"local": [{"user": {"name": "{0}"}}, {"group": {"name": "openstack-security-operators", "domain": {"name": "${DOMAIN}"}}}],
   "remote": [{"type": "OIDC-preferred_username"}, {"type": "OIDC-groups", "any_one_of": ["openstack-security-operators"]}]}
]
EOF
)
curl -sf -X PATCH -H "X-Auth-Token: ${OS_TOKEN}" -H 'Content-Type: application/json' \
  -d "{\"mapping\": {\"rules\": ${MAPPING_RULES}}}" \
  "${OS_AUTH_URL}/OS-FEDERATION/mappings/keycloak-dcn" >/dev/null
echo "keycloak-dcn mapping reconciled to the seven-persona design"

echo "== done =="
