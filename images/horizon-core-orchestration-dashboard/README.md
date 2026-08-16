# Horizon Track A panel

This package is intentionally independent from `horizon-complete`. It renders
project Operations, Launch Templates, Auto Scaling Groups and Recycle Bin data
against the frozen `/core-orchestrator/v1` fake contract. It is not wired into
the shared Horizon image until development API acceptance and integration-owner
review.

Builds must pass an immutable existing Horizon base:

```bash
docker build --build-arg HORIZON_BASE='registry.example/horizon@sha256:<digest>' .
./verify-overlay.sh
```

The panel does not create identity assertions. The production reverse proxy is
responsible for Keystone authentication, OPA authorization, header stripping
and signing the internal assertion.
