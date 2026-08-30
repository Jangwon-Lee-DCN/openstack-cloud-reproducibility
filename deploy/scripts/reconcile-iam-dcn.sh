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
# Eight personas as of 2026-08-03, extended from the original four per
# "Coordinated implementation direction for the VPC platform" in the IAM
# hardening doc: admins/operators/members/readers (project-scoped, as
# before) plus domain-admins (domain-scoped -- see DOMAIN_PERSONA_ROLES),
# network-operators and security-operators (project-scoped, carrying new
# custom marker roles that VPC-facade OPA policy is meant to consult --
# see that doc section for what each should authorize; Keystone itself
# enforces nothing extra for them), and project-creators (domain-scoped
# marker role consulted only by the `project-facade` service -- see "New
# permission tier: self-service project lifecycle" in the IAM hardening
# doc). cloud-admin (system-scope) is deliberately not implemented here --
# see the same doc section for why.
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

echo "== ensuring Keycloak realm and Keystone OIDC client =="
if ! curl -sf -H "Authorization: Bearer ${KC_TOKEN}" \
  "http://${KEYCLOAK_SVC}/admin/realms/${REALM}" >/dev/null; then
  curl -sf -X POST -H "Authorization: Bearer ${KC_TOKEN}" -H 'Content-Type: application/json' \
    -d "{\"realm\":\"${REALM}\",\"enabled\":true}" \
    "http://${KEYCLOAK_SVC}/admin/realms" >/dev/null
fi
realm_payload=$(curl -sf -H "Authorization: Bearer ${KC_TOKEN}" \
  "http://${KEYCLOAK_SVC}/admin/realms/${REALM}" | jq \
  '.loginTheme="dcn-openstack" |
   .displayName="DCN OpenStack" |
   .displayNameHtml="DCN OpenStack"')
curl -sf -X PUT -H "Authorization: Bearer ${KC_TOKEN}" -H 'Content-Type: application/json' \
  -d "${realm_payload}" "http://${KEYCLOAK_SVC}/admin/realms/${REALM}" >/dev/null
unset realm_payload
OIDC_CLIENT_SECRET=$(kubectl -n keycloak get secret keycloak-credentials \
  -o jsonpath='{.data.oidc-client-secret}' | base64 -d)
client_payload=$(jq -nc --arg secret "$OIDC_CLIENT_SECRET" '{
  clientId:"keystone", name:"Keystone", enabled:true,
  protocol:"openid-connect", publicClient:false, secret:$secret,
  standardFlowEnabled:true, directAccessGrantsEnabled:false,
  redirectUris:["https://cloud.dcn.ssu.ac.kr/identity/v3/OS-FEDERATION/oidc-callback"],
  webOrigins:["https://cloud.dcn.ssu.ac.kr"]
}')
existing_client=$(curl -sf -H "Authorization: Bearer ${KC_TOKEN}" \
  "http://${KEYCLOAK_SVC}/admin/realms/${REALM}/clients?clientId=${KEYSTONE_CLIENT_ID}" | jq -r '.[0].id // empty')
if [[ -z "$existing_client" ]]; then
  curl -sf -X POST -H "Authorization: Bearer ${KC_TOKEN}" -H 'Content-Type: application/json' \
    -d "$client_payload" "http://${KEYCLOAK_SVC}/admin/realms/${REALM}/clients" >/dev/null
else
  curl -sf -X PUT -H "Authorization: Bearer ${KC_TOKEN}" -H 'Content-Type: application/json' \
    -d "$client_payload" "http://${KEYCLOAK_SVC}/admin/realms/${REALM}/clients/${existing_client}" >/dev/null
fi
unset OIDC_CLIENT_SECRET client_payload

echo "== ensuring Keystone domain and administrative project =="
DOMAIN_ID=$(curl -sf -H "X-Auth-Token: ${OS_TOKEN}" "${OS_AUTH_URL}/domains?name=${DOMAIN}" | jq -r '.domains[0].id // empty')
if [[ -z "$DOMAIN_ID" ]]; then
  DOMAIN_ID=$(curl -sf -X POST -H "X-Auth-Token: ${OS_TOKEN}" -H 'Content-Type: application/json' \
    -d "{\"domain\":{\"name\":\"${DOMAIN}\",\"enabled\":true,\"description\":\"Federated DCN identity domain\"}}" \
    "${OS_AUTH_URL}/domains" | jq -r '.domain.id')
  echo "created Keystone domain ${DOMAIN}"
fi
PROJECT_ID=$(curl -sf -H "X-Auth-Token: ${OS_TOKEN}" "${OS_AUTH_URL}/projects?name=${PROJECT}&domain_id=${DOMAIN_ID}" | jq -r '.projects[0].id // empty')
if [[ -z "$PROJECT_ID" ]]; then
  PROJECT_ID=$(curl -sf -X POST -H "X-Auth-Token: ${OS_TOKEN}" -H 'Content-Type: application/json' \
    -d "{\"project\":{\"name\":\"${PROJECT}\",\"domain_id\":\"${DOMAIN_ID}\",\"enabled\":true,\"description\":\"Federated DCN administrative project\"}}" \
    "${OS_AUTH_URL}/projects" | jq -r '.project.id')
  echo "created Keystone project ${DOMAIN}/${PROJECT}"
fi
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

# Required persona roles. Some service charts create their own roles, but the
# IAM phase owns the final contract and therefore fills in any missing marker.
# These are markers consulted by VPC-facade OPA policy (Path B), not
# Keystone policy.yaml overrides -- see "Coordinated implementation
# direction for the VPC platform" in the IAM hardening doc for what each
# is meant to authorize (Peering/TGW for network-operator; SG/NACL/Flow Log
# for security-operator). Ensuring they exist here only makes them
# assignable; it grants no OpenStack-service-level capability by itself.
echo "== ensuring custom roles exist =="
for role_name in admin member reader load-balancer_admin monitoring network-operator security-operator project-creator; do
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
#
# openstack-project-creators (new) -- self-service project lifecycle,
# scoped to this Keystone domain only. Grants the custom `project-creator`
# marker role at DOMAIN scope; it authorizes nothing in Keystone or any
# OpenStack service policy by itself (same "marker role" pattern as
# network-operator/security-operator). The `project-facade` service is the
# only thing that consults it: it checks the caller's domain-scoped
# effective roles for `project-creator` before creating a project under
# this domain on their behalf, then grants them `admin` on the project
# they just created (their own project, not this domain's `dcn` admin
# project, which is separately protected -- see the
# `options.immutable=true` fix applied directly to the `dcn` project, "New
# permission tier: self-service project lifecycle" in the IAM hardening
# doc). Deliberately NOT the same group as openstack-domain-admins --
# project-creator must never imply domain-wide admin.
declare -A DOMAIN_PERSONA_ROLES=(
  [openstack-domain-admins]="admin"
  [openstack-project-creators]="project-creator"
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
   "remote": [{"type": "OIDC-preferred_username"}, {"type": "OIDC-groups", "any_one_of": ["openstack-security-operators"]}]},
  {"local": [{"user": {"name": "{0}"}}, {"group": {"name": "openstack-project-creators", "domain": {"name": "${DOMAIN}"}}}],
   "remote": [{"type": "OIDC-preferred_username"}, {"type": "OIDC-groups", "any_one_of": ["openstack-project-creators"]}]}
]
EOF
)
mapping_method=PUT
curl -sf -H "X-Auth-Token: ${OS_TOKEN}" "${OS_AUTH_URL}/OS-FEDERATION/mappings/keycloak-dcn" >/dev/null 2>&1 && mapping_method=PATCH
curl -sf -X "$mapping_method" -H "X-Auth-Token: ${OS_TOKEN}" -H 'Content-Type: application/json' \
  -d "{\"mapping\": {\"rules\": ${MAPPING_RULES}}}" \
  "${OS_AUTH_URL}/OS-FEDERATION/mappings/keycloak-dcn" >/dev/null
echo "federation mapping object reconciled"
idp_url="${OS_AUTH_URL}/OS-FEDERATION/identity_providers/keycloak-dcn"
if idp_json=$(curl -sf -H "X-Auth-Token: ${OS_TOKEN}" "$idp_url" 2>/dev/null); then
  test "$(printf '%s' "$idp_json" | jq -r '.identity_provider.domain_id')" = "$DOMAIN_ID"
  curl -sf -X PATCH -H "X-Auth-Token: ${OS_TOKEN}" -H 'Content-Type: application/json' \
    -d '{"identity_provider":{"enabled":true,"remote_ids":["https://auth.cloud.dcn.ssu.ac.kr/realms/dcn"]}}' \
    "$idp_url" >/dev/null
else
  curl -sf -X PUT -H "X-Auth-Token: ${OS_TOKEN}" -H 'Content-Type: application/json' \
    -d '{"identity_provider":{"enabled":true,"remote_ids":["https://auth.cloud.dcn.ssu.ac.kr/realms/dcn"],"domain_id":"'"${DOMAIN_ID}"'"}}' \
    "$idp_url" >/dev/null
fi
echo "federation identity provider reconciled"
protocol_method=PUT
curl -sf -H "X-Auth-Token: ${OS_TOKEN}" "${OS_AUTH_URL}/OS-FEDERATION/identity_providers/keycloak-dcn/protocols/openid" >/dev/null 2>&1 && protocol_method=PATCH
curl -sf -X "$protocol_method" -H "X-Auth-Token: ${OS_TOKEN}" -H 'Content-Type: application/json' \
  -d '{"protocol":{"mapping_id":"keycloak-dcn"}}' \
  "${OS_AUTH_URL}/OS-FEDERATION/identity_providers/keycloak-dcn/protocols/openid" >/dev/null
echo "federation protocol reconciled"
echo "keycloak-dcn mapping reconciled to the eight-persona design"

# Optional: let staff sign in with their own dcn.ssu.ac.kr company Google
# account instead of a Keycloak-local password. This only brokers Google as
# an additional login method INTO Keycloak -- Keystone's OIDC federation
# to Keycloak (protocol keycloak-dcn) is unchanged and doesn't know or care
# which upstream IdP the user authenticated through. Skipped entirely (not
# an error) until `google-idp-oauth` exists, since the OAuth client can only
# be created by hand in Google Cloud Console (Workspace-admin action, see
# docs/proposals/iam-hardening/README.md "Google Workspace SSO" for the
# exact redirect URI and consent-screen settings this depends on).
GOOGLE_CLIENT_ID=$(kubectl -n keycloak get secret google-idp-oauth -o jsonpath='{.data.client-id}' 2>/dev/null | base64 -d || true)
GOOGLE_CLIENT_SECRET=$(kubectl -n keycloak get secret google-idp-oauth -o jsonpath='{.data.client-secret}' 2>/dev/null | base64 -d || true)
if [[ -z "${GOOGLE_CLIENT_ID}" || -z "${GOOGLE_CLIENT_SECRET}" ]]; then
  echo "== google-idp-oauth secret not found in the keycloak namespace -- skipping Google IdP setup =="
else
  echo "== ensuring Google identity provider (broker) on the dcn realm =="
  # hostedDomain restricts login server-side to dcn.ssu.ac.kr accounts --
  # Keycloak validates the ID token's own "hd" claim against this, it isn't
  # just an auth-request hint the user could strip. trustEmail is safe
  # because Google itself only issues verified-email tokens.
  google_idp_config=$(python3 -c "
import json
print(json.dumps({
  'alias': 'google',
  'providerId': 'google',
  'enabled': True,
  'trustEmail': True,
  'storeToken': False,
  'firstBrokerLoginFlowAlias': 'first broker login',
  'config': {
    'clientId': '''${GOOGLE_CLIENT_ID}''',
    'clientSecret': '''${GOOGLE_CLIENT_SECRET}''',
    'hostedDomain': 'dcn.ssu.ac.kr',
    'syncMode': 'IMPORT',
  },
}))
")
  existing_idp=$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer ${KC_TOKEN}" \
    "http://${KEYCLOAK_SVC}/admin/realms/${REALM}/identity-provider/instances/google")
  if [[ "${existing_idp}" == "200" ]]; then
    curl -sf -X PUT -H "Authorization: Bearer ${KC_TOKEN}" -H 'Content-Type: application/json' \
      -d "${google_idp_config}" "http://${KEYCLOAK_SVC}/admin/realms/${REALM}/identity-provider/instances/google" >/dev/null
    echo "updated Google identity provider config"
  else
    curl -sf -X POST -H "Authorization: Bearer ${KC_TOKEN}" -H 'Content-Type: application/json' \
      -d "${google_idp_config}" "http://${KEYCLOAK_SVC}/admin/realms/${REALM}/identity-provider/instances" >/dev/null
    echo "created Google identity provider"
  fi

  echo "== ensuring Google logins auto-join openstack-members =="
  # Hardcoded-group mapper, not a claim-based one: Google has no concept of
  # our Keystone personas, so every dcn.ssu.ac.kr Google login lands in the
  # baseline "member" persona by default; an admin promotes specific people
  # into openstack-operators/-readers/-network-operators/-security-operators/
  # -domain-admins by hand afterward, the same as any other Keycloak group
  # membership change (Path A's existing group-drives-role design applies
  # unchanged once the user is in a group).
  existing_mapper=$(curl -sf -H "Authorization: Bearer ${KC_TOKEN}" \
    "http://${KEYCLOAK_SVC}/admin/realms/${REALM}/identity-provider/instances/google/mappers" \
    | jq -r '.[] | select(.name=="auto-assign-openstack-members") | .id')
  if [[ -z "${existing_mapper}" ]]; then
    curl -sf -X POST -H "Authorization: Bearer ${KC_TOKEN}" -H 'Content-Type: application/json' \
      -d '{
        "name": "auto-assign-openstack-members",
        "identityProviderAlias": "google",
        "identityProviderMapper": "oidc-hardcoded-group-idp-mapper",
        "config": {"syncMode": "INHERIT", "group": "/openstack-members"}
      }' "http://${KEYCLOAK_SVC}/admin/realms/${REALM}/identity-provider/instances/google/mappers" >/dev/null
    echo "created auto-assign-openstack-members mapper"
  else
    echo "auto-assign-openstack-members mapper already present (${existing_mapper})"
  fi

  echo "== ensuring Google logins auto-join openstack-project-creators =="
  # Matches the original ask directly: "dcn.ssu.ac.kr domain users" (not a
  # separately-elevated subset) should be able to self-service create their
  # own project. A second hardcoded-group mapper on the same IdP, same
  # INHERIT pattern as openstack-members above -- every new Google login
  # lands in both groups from the start. Confirmed live (2026-08-03) that
  # this needed to be explicit: a real user who completed first-broker-
  # login before this mapper existed got openstack-members only, and their
  # project-facade "Create Project" click was correctly denied
  # ("missing project-creator role on this domain") -- exactly the
  # designed behavior for someone without the role, not a bug, but not
  # the originally intended default either. This mapper only fixes it
  # going forward for *new* first-time Google logins; INHERIT sync does
  # not retroactively re-run for users who already completed their first
  # broker login, so anyone in that situation needs a one-time manual
  # group add (see the same section in the IAM hardening doc).
  existing_mapper2=$(curl -sf -H "Authorization: Bearer ${KC_TOKEN}" \
    "http://${KEYCLOAK_SVC}/admin/realms/${REALM}/identity-provider/instances/google/mappers" \
    | jq -r '.[] | select(.name=="auto-assign-openstack-project-creators") | .id')
  if [[ -z "${existing_mapper2}" ]]; then
    curl -sf -X POST -H "Authorization: Bearer ${KC_TOKEN}" -H 'Content-Type: application/json' \
      -d '{
        "name": "auto-assign-openstack-project-creators",
        "identityProviderAlias": "google",
        "identityProviderMapper": "oidc-hardcoded-group-idp-mapper",
        "config": {"syncMode": "INHERIT", "group": "/openstack-project-creators"}
      }' "http://${KEYCLOAK_SVC}/admin/realms/${REALM}/identity-provider/instances/google/mappers" >/dev/null
    echo "created auto-assign-openstack-project-creators mapper"
  else
    echo "auto-assign-openstack-project-creators mapper already present (${existing_mapper2})"
  fi
fi

echo "== done =="
