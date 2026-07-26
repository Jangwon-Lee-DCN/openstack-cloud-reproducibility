# ISSUE: Ironic Toleration Rendering Indentation

OpenStack-Helm 2026.1.0 rendered the Ironic API, conductor, and cleaning-network
Job toleration snippets with indentation that placed them outside the Pod spec.
The resulting manifests were invalid or could not schedule on tainted control
plane nodes.
