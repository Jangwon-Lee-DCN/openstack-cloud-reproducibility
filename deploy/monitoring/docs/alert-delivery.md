# Alert delivery and runbooks

The platform routes `critical` and `warning` alerts separately. Until an
operator deliberately configures an external receiver, both routes terminate
at the in-cluster `alertmanager-webhook-audit` service. This proves delivery
without sending infrastructure information outside the cluster.

| Severity | Group wait | Repeat | Current receiver |
|---|---:|---:|---|
| Critical | 10 seconds | 1 hour | `critical-audit` |
| Warning | 30 seconds | 4 hours | `warning-audit` |

Resolved notifications are enabled. `Watchdog` remains routed to `null`.
Critical versions of the same alert inhibit warning/info versions. EIP quota
exhaustion inhibits the matching low-quota warning, and a controller rollout
failure inhibits secondary reconcile-error and latency alerts.

## General response

1. Open the alert's `runbook_url` and Grafana dashboard.
2. Confirm whether the alert is firing in both Prometheus and Alertmanager.
3. Use the labels in the notification to restrict logs and metrics.
4. Silence only with an owner and expiration time. Do not silence `critical`
   alerts indefinitely.
5. Confirm receipt of the resolved notification after remediation.

## OpenStack availability

- Exporter/API probe: verify the exporter Pod, Keystone endpoint and network
  path before restarting anything.
- RabbitMQ/MariaDB: check quorum/member health first; avoid simultaneous
  restarts.
- Synthetic lifecycle: inspect the latest CronJob and Job logs, then distinguish
  a test cleanup failure from a real API outage.
- Floating IP probe: compare Neutron floating-IP state, router gateway state and
  the target VM before changing routing.

## Controller temperature

Check current and sustained temperature, fan state and node workload. Drain a
node before hardware intervention. A critical alert suppresses the matching
high-temperature warning.

## VPC control plane

- Reconcile errors/latency: filter controller logs by controller and project
  namespace; correlate Neutron request IDs and HTTP 409 counters.
- SG violation: confirm the reported port is outside the VPC and that the
  controller detached it.
- EIP failure/quota: check the stable reason label, project quota and named pool.
- Credential binding: restore only the fixed `openstack-credentials` binding;
  never copy credentials between project namespaces.
- Rollout unavailable: restore Deployment availability before investigating
  secondary reconcile symptoms.

## Slack receiver — operator action only

No Slack URL or token is stored or deployed by this repository. When approved:

1. Create a dedicated Slack app/channel and an incoming webhook with the
   smallest possible scope.
2. Store the webhook URL in a SOPS-encrypted values file or ExternalSecret.
3. Replace `critical-audit`/`warning-audit` with `slack_configs`, using separate
   channels or visibly different titles.
4. Keep `send_resolved: true`; include severity, alert name, project namespace,
   summary, description, runbook URL and Alertmanager silence link.
5. Run the local delivery test first, then a controlled Slack test alert, and
   delete the test rule.

Never commit a webhook URL. Rotating the Slack webhook must not require editing
the PrometheusRule files.

## Email receiver — operator action only

No SMTP credentials are stored or deployed by this repository. When approved:

1. Obtain a relay account limited to the monitoring sender and approved
   recipients.
2. Store SMTP password/credentials through SOPS or ExternalSecret.
3. Configure `email_configs` under separate critical/warning receivers.
4. Require TLS and certificate verification. Do not use `insecure_skip_verify`.
5. Set `send_resolved: true`, then perform a controlled delivery and resolution
   test.

## Delivery test

`scripts/test-alert-delivery.sh` creates a temporary warning PrometheusRule,
waits for `POST /warning` in the local audit receiver, and removes the rule via
an exit trap. It does not contact Slack, SMTP or any other external service.

Run:

```bash
deploy/monitoring/scripts/test-alert-delivery.sh
```

Inspect route health:

```bash
kubectl -n monitoring logs deployment/alertmanager-webhook-audit
kubectl -n monitoring port-forward svc/kube-prometheus-stack-alertmanager 9093
curl -fsS http://127.0.0.1:9093/api/v2/status
```
