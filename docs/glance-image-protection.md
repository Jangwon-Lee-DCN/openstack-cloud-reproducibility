# Glance image deletion protection

Phase 50 protects every active public Glance image and every active hidden
image tagged `amphora`. Tenant boot, CAPI and Octavia image consumption are
unchanged; Glance rejects deletion while `protected=true`.

## Development acceptance

The isolated component exercises the same target selection, apply and failure
paths without credentials or access to production Glance:

```sh
DEVELOPMENT_COMPONENT_ROOT="$PWD/automation/development/components" \
  /home/ubuntu/openstack-production-datacenter/deploy.sh development glance-image-protection
```

## Production apply and acceptance

Production application is only through an approved `development -> main`
promotion and Phase 50. After Phase 50, independently verify:

```sh
deploy/scripts/reconcile-glance-image-protection.sh verify
```

Acceptance requires every active public image and the private, hidden
`amphora` image to report `protected=true`. Octavia's hidden-image lookup must
still resolve the configured Amphora image ID.

## Rollback

Protection removal is intentionally gated and affects only the same selected
images:

```sh
APPROVE_GLANCE_IMAGE_UNPROTECT=yes \
  deploy/scripts/reconcile-glance-image-protection.sh rollback
```

Rollback is not required for normal image replacement. Upload and validate a
new protected image first, switch consumers, and only then explicitly
unprotect and retire the old image.
