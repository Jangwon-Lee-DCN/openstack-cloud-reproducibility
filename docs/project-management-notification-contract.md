# Project Management Notification Contract

Horizon `Project Health` is the tenant-facing inbox. It reports missing
administrators, exhausted/near quota, expiring credentials, disabled projects
and failed resources without requiring an external notification receiver.

Alertmanager carries platform delivery failures. `ProjectFacadeUnavailable`
is Critical after five minutes and `ProjectFacadeRestarting` is Warning after
ten minutes. Both use `service=project-management`, which is the stable route
matcher for a future Slack or email receiver. Receiver credentials and target
addresses are deliberately not stored in Git.

Configure one Alertmanager child route matching
`service="project-management"`, group by `alertname`, wait 30 seconds, group
for five minutes and repeat Critical notifications after four hours. Inhibit
Warning alerts while `ProjectFacadeUnavailable` is firing. A test receiver
must be used before adding production Slack/email destinations.

Project-specific lifecycle notices remain in Horizon until the facade exports
stable project-health gauges. Do not generate one Prometheus series per user
or credential secret; only project ID, finding type and severity may become
labels.
