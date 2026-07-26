# Change Policy

Every local compatibility change must satisfy all of the following:

- ISSUE: observable failure, affected upstream version, and root cause
- FIX: exact source, values, image, or manifest change
- RECONCILE: idempotent commands and required inputs
- VERIFY: positive tests, failure checks, and remaining limitations

Upstream source imports and local changes must be separate commits. Images and
charts must be pinned by version and preferably by immutable digest. Runtime
secrets must be SOPS-encrypted; decrypted files must never be committed.
