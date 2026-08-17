# Cross-track consumer contract provenance

Track C vendors provider schemas for offline consumer validation. Runtime code
must not read another worktree or Git branch.

| Contract | Provider commit | Canonical provider path |
| --- | --- | --- |
| `track-a.operation.v1alpha1` | `7225b63` | `contracts/track-a/track-a.operation.v1alpha1.schema.json` |
| `track-b.event.v1alpha1` | `0c9f6be` | `services/governance-api/contracts/track-b/track-b.event.v1alpha1.schema.json` |

The vendored JSON objects are semantically identical to those provider files.
Fixtures are Track C-owned examples and validate with Draft 2020-12 plus UUID
and date-time format checking. Updating either provider requires a deliberate
vendor update, fixture validation and consumer test commit.

Track C lifecycle actions that are not canonical Track B event types are
represented as `resource.changed`; their original action and outcome are
preserved inside the schema's open `payload` extension point.
