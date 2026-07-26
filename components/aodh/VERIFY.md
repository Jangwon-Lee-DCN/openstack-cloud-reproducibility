# VERIFY: Aodh

- API, evaluator, listener, and notifier each have two Ready replicas split
  across controllers.
- The API PodDisruptionBudget permits one controlled disruption.
- `/alarming/healthcheck` returns HTTP 200 through the public Gateway.
- Create an alarm over a real Gnocchi metric, cross its threshold, observe the
  state transition, and delete the test alarm.

Health checks pass in the current PoC. Real metric alarm evaluation remains
coupled to the pending Ceilometer-to-Gnocchi measure gate.
