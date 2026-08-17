# aodh operational contract

This is the authoritative issue, remediation, reconciliation, and verification contract for `aodh`.

## Known issues and scope

## Affected baseline

- OpenStack-Helm chart `2026.1.0`
- Aodh `22.0.0`

## Symptoms

The default image was unavailable or incompatible with the target Python/WSGI
runtime. The initial replacement failed because Apache mod_wsgi was compiled
for a different Python runtime. The optional alarm-cleaner CronJob also
rendered an unresolved configuration volume.

## Root cause

The chart image assumptions did not match the available runtime. Debian's
system mod_wsgi and the Python 3.12 application environment were ABI-incompatible.
The cleaner template references configuration that is not fully rendered by
the chart.

## Remediation

- Build Aodh 22.0.0 on Python 3.12.
- Compile and install mod_wsgi for that exact interpreter.
- Configure Apache with the matching Python site-packages path.
- Run API, evaluator, listener, and notifier with two hard-anti-affinity
  replicas; use MySQL Tooz coordination for distributed workers.
- Register `/alarming` in Keystone and the public Gateway.
- Disable only the defective optional alarm-cleaner CronJob until its upstream
  template is corrected.

The core alarm API and workers remain enabled. The public health endpoint has
returned HTTP 200.

## Reconciliation

1. Build or pull the digest-pinned Python 3.12/mod_wsgi Aodh image.
2. Re-encrypt the Aodh values profile for the target database, Keystone,
   RabbitMQ, and registry credentials.
3. Run `deploy/scripts/reconcile.sh`; it upgrades the clean upstream chart
   using the local values file.
4. Keep the optional alarm cleaner disabled until its template volume defect
   is fixed and verified in a separate chart patch commit.

## Verification

- API, evaluator, listener, and notifier each have two Ready replicas split
  across controllers.
- The API PodDisruptionBudget permits one controlled disruption.
- `/alarming/healthcheck` returns HTTP 200 through the public Gateway.
- Create an alarm over a real Gnocchi metric, cross its threshold, observe the
  state transition, and delete the test alarm.

Health checks pass in the current PoC. Real metric alarm evaluation remains
coupled to the pending Ceilometer-to-Gnocchi measure gate.
