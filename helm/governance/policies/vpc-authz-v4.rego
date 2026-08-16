package vpc.authz

import future.keywords.in
import future.keywords.if

default allow := false

allow if {
  input.context.authorization_class == "read"
  some role in input.subject.roles
  role in {"reader", "member", "manager", "admin", "domain-admin", "load-balancer_admin", "monitoring", "network-admin", "network-operator", "security-admin", "security-operator"}
}

allow if {
  input.context.authorization_class == "project-write"
  some role in input.subject.roles
  role in {"admin", "domain-admin", "manager", "member", "load-balancer_admin"}
}

allow if {
  input.context.authorization_class == "network-sharing"
  some role in input.subject.roles
  role in {"admin", "domain-admin", "manager", "network-admin", "network-operator"}
}

allow if {
  input.context.authorization_class == "security-policy"
  some role in input.subject.roles
  role in {"admin", "domain-admin", "manager", "security-admin", "security-operator"}
}

# New in v4: a fifth authorization class the facade only invokes
# directly from createVpcPeering, once it has resolved the peer
# project's Keystone domain (native RBAC's plain role list can't
# express this -- it requires knowing the *peer* project's domain,
# not just the caller's own roles/project). docs/domain-model.md
# already decided cross-domain peering should be a stricter tier
# than same-domain peering; this is that tier's authorization rule.
# Evaluated after the facade resolves the peer project's domain. Production
# enforces this class fail-closed; the same policy remains observable via
# the class-labelled decision metrics and audit record.
allow if {
  input.context.authorization_class == "cross-domain-peering"
  some role in input.subject.roles
  role in {"admin", "domain-admin"}
}

decision := {
  "allow": allow,
  "policy": "vpc.authz",
  "policy_version": "vpc-authz-v4",
  "mode": "enforce",
}
