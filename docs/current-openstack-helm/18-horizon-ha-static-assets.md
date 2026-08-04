# Horizon HA static assets

## Contract

Horizon runs two replicas and serves collected/compressed assets from a
pod-local `emptyDir`. Database-backed Django sessions are shared safely across
replicas, but django-compressor metadata must not use the shared default
memcached backend: a cached bundle name is only valid in the pod that owns the
corresponding file.

The accepted configuration is:

- `COMPRESS_OFFLINE = False`, because compressed templates include the
  request-aware `/horizon` prefix;
- `STATIC_URL = /horizon/static/` and matching login/logout/redirect paths;
- `COMPRESS_CACHE_BACKEND = compressor`;
- the `compressor` alias uses Django `LocMemCache`, isolating metadata per WSGI
  process and therefore per pod;
- readiness and liveness timeouts allow initial per-process compression to
  complete.

Do not replace this with a shared compressor cache, a post-Helm ConfigMap
mutation, or independently configured replicas.

## Failure signature

The observed failure was intermittent: HTML returned by one replica referenced
`angular_template_cache_preloads.<hash>.js`, but the subsequent load-balanced
request reached the other replica and returned an HTML 404 response. Chromium
then reported `Unexpected token '<'`; Angular failed to initialize and Magnum's
Create Cluster dialog displayed only its header and buttons.

## Reconcile and verify

The behavior is implemented in the patched Horizon chart and site values, so a
normal `reconcile-full-stack.sh` run is sufficient. No imperative patch is
required.

`verify-full-stack.sh` checks both server replicas, the resolved Django cache
backend, `/horizon/static/`, and the exact preload bundle filename and size.
For UI acceptance, authenticate through the public URL, open Project >
Container Infra > Clusters, and verify Create Cluster displays Details, Size,
Network, Management, Review and Advanced without JavaScript errors or static
asset responses with status 400 or greater.
