# ISSUE: Ceilometer Image and Notification Transport Failures

## Affected baseline

- OpenStack-Helm chart `2026.1.0`
- Ceilometer `26.0.0`
- Upstream Airship image pinned in `images/ceilometer/upstream/BASELINE.md`

## Symptoms

- The compute pollster raised `ImportError: python-libvirt module is missing`.
- Notification workers repeatedly lost RabbitMQ connections.
- An initial generated transport configuration used port 15672, the RabbitMQ
  management HTTP API, instead of AMQP port 5672.
- Enabling every central pollster produced expected errors for services not
  installed in the PoC.

## Root cause

The image omitted Python libvirt bindings. The generated multi-bus URLs chose
the wrong endpoint port. The default broad pollster set assumes optional
OpenStack services that are absent here.
