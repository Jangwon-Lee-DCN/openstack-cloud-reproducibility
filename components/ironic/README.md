# ironic operational contract

This is the authoritative issue, remediation, reconciliation, and verification contract for `ironic`.

## Known issues and scope

OpenStack-Helm 2026.1.0 rendered the Ironic API, conductor, and cleaning-network
Job toleration snippets with indentation that placed them outside the Pod spec.
The resulting manifests were invalid or could not schedule on tainted control
plane nodes.

## Remediation

The three affected templates change the included toleration block indentation
from ten spaces to six spaces. This is a chart-source patch and the resulting
package is stored at `helm/packages/patched/ironic-2026.1.0.tgz`.
