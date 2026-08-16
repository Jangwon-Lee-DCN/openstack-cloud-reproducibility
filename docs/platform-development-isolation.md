# Platform and development workload isolation

The management cluster separates third-party development workloads from the
OpenStack platform without relocating node-bound OpenStack, OVN, Ceph, CSI, or
backup components.

`dcn-1b-utility-0` is the initial development worker. It carries
`dcn.ssu.ac.kr/workload-class=development` and a matching `NoSchedule` taint.
Development Pods must select and tolerate that class; a native Kubernetes
ValidatingAdmissionPolicy rejects Pods that omit either contract. The three
`controller-1` nodes are labelled as the preferred platform application pool.
Existing infrastructure components retain their necessary controller,
Compute, Storage, and topology placement.

Development namespaces carry the development workload-class label, default
deny networking, DNS and public Internet egress only, resource quotas,
restricted Pod Security admission, and explicit Gateway ingress. Platform and
system namespaces are classified separately. Development data must live in a
managed external store; the utility node is neither authoritative storage nor
a PowerStore block client. Backup orchestration retains priority over
interruptible development work.

The development ingress boundary is a dedicated Cilium Gateway at
`10.67.10.9`, with wildcard DNS and TLS for `*.dev.dcn.ssu.ac.kr`. Only
namespaces labelled `development-gateway-access=allowed` may attach routes.
The existing OpenStack, internal, platform, and registry Gateways are
unchanged. Development ingress is intended for the existing VPN/private routed
network, not unrestricted public exposure.

Rebuild and acceptance commands are:

```bash
ansible-playbook -i inventory/production/hosts.yml playbooks/15-dns.yml
ansible-playbook -i inventory/production/hosts.yml playbooks/58-workload-isolation.yml
ansible-playbook -i inventory/production/hosts.yml playbooks/60-verify.yml
```

To add another development worker, extend `platform_preferred_nodes` and the
development-node model before applying the same label, taint, affinity and
validation contract. Do not simply remove the taint. Production promotion
uses an immutable image digest; it does not move a live development Pod.
