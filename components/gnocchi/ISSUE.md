# ISSUE: OpenStack-Helm Gnocchi Runtime Is Obsolete

## Affected baseline

- OpenStack-Helm tag `2026.1.0`, commit `c665eed`
- Chart version `2026.1.0`
- Chart application version `3.0.3`

## Symptoms

The chart defaults target an obsolete Gnocchi/Python runtime and cannot provide
the required modern Python 3.12, Keystone, MySQL, Tooz, and S3-compatible RGW
combination in this environment.

## Root cause

The chart metadata and runtime assumptions have not followed the current
Gnocchi packaging. Treating the unmodified chart as deployable would preserve
legacy Python paths and image expectations.
