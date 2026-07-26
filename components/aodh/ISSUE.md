# ISSUE: Aodh Runtime and Optional Cleaner Chart Defect

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
