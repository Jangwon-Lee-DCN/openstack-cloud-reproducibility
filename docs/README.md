# Documentation map

This page identifies the authoritative entry point for each operational task.
Historical evidence may remain in Git, but operators should start here.

## Build and reproduce

- [Reproducibility model](REPRODUCIBILITY.md): artifact and change boundaries
- [Upstream provenance](PROVENANCE.md): upstream inputs and local deviations
- [Change policy](CHANGE_POLICY.md): how changes become reproducible
- [Fresh-server rebuild runbook](fresh-server-rebuild-runbook.md): executable rebuild order
- [Fresh-server operator guide](fresh-server-rebuild-operator-guide.md): human gates and recovery
- [Current OpenStack-Helm deployment](current-openstack-helm/README.md): current architecture and service runbooks

## Operate and expand

- [Full-stack reconciliation](FULL_STACK.md): reconcile and verify the accepted stack
- [Node expansion](node-expansion-operator-guide.md): add Kubernetes/OpenStack capacity
- [Platform/development isolation](platform-development-isolation.md): workload placement contract
- [VPC IAM and OPA](vpc-iam-opa-operations.md): authorization operations
- [Horizon information architecture](horizon-information-architecture.md): dashboard panel contract
- [Glance image protection](glance-image-protection.md): protected-image policy

## Development and governance

- [Core orchestrator integration requirements](core-orchestrator-integration-requirements.md)
- [Core orchestrator development acceptance](core-orchestrator-development-acceptance.md)
- [Governance development slice](governance-development-slice.md)
- [Governance integration acceptance](governance-real-integration-development.md)
- [CloudKitty FinOps operations](governance-cloudkitty-finops.md)
- [Project notification contract](project-management-notification-contract.md)

Files whose names begin with `todo-` or end in `-todo.md` are planning queues,
not current-state operating instructions. Dated capability records are release
evidence and do not override the runbooks above.

