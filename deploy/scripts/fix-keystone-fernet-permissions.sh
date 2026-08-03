#!/usr/bin/env bash
set -euo pipefail

# Works around a real kubelet/CRI-O bug on this cluster: Secret volume
# `defaultMode`/per-item `mode` are silently ignored for whole-directory
# mounts (confirmed via an isolated test: even an explicit `items:` with
# `mode: 0o440` still rendered as 777), which makes Keystone's
# `fernet-keys` key repository world-readable
# (`keystone.common.fernet_utils` logs a warning about this on every
# restart). See openstack-cloud-services/docs/proposals/iam-hardening/README.md,
# "Baseline hardening", for the full root-cause writeup.
#
# Whole-directory mounting is deliberate (not something to just switch to
# subPath) -- it's what lets `keystone-api` pick up newly-rotated Fernet
# keys without a pod restart. The fix works around the kubelet bug instead
# of trading that property away: a small sidecar (`fernet-sync`) mirrors
# the raw Secret into a separate `emptyDir` with correct permissions
# (chmod 600 per file, owned by the same uid/gid keystone-api itself runs
# as), and a one-shot root init container (`fernet-perms-init`) sets
# ownership/mode on the emptyDir itself once at pod start (a non-root
# process can't chmod a directory it doesn't own). `keystone-api`'s
# existing container mounts the emptyDir instead of the Secret directly,
# at the same path -- no change to its own spec.
#
# This is a live `kubectl patch` of the Deployment, not something
# expressible via this chart's values -- like
# `fix-horizon-probe-path.sh`'s pattern, it must be RE-RUN after any
# `helm upgrade` of keystone, since that resets the Deployment spec back
# to the chart's rendered default and would silently undo this. Safe to
# re-run: checks for the `fernet-perms-init` init container first and
# does nothing if it's already present.
#
# Two capabilities are required on the init container beyond bare
# `runAsUser: 0` -- root with `capabilities: {drop: [ALL]}` and no `add`
# cannot chown or chmod a directory it doesn't already own (found live,
# the hard way: `chown` needs CAP_CHOWN, the subsequent `chmod` separately
# needs CAP_FOWNER once ownership no longer matches the process's own
# UID/GID at the moment `drop: [ALL]` stripped everything).

NAMESPACE=openstack
DEPLOYMENT=keystone-api

existing=$(kubectl -n "${NAMESPACE}" get deployment "${DEPLOYMENT}" \
  -o jsonpath='{.spec.template.spec.initContainers[?(@.name=="fernet-perms-init")].name}' 2>/dev/null || true)
if [[ -n "${existing}" ]]; then
  echo "fernet-perms-init already present on ${DEPLOYMENT} -- nothing to do."
  exit 0
fi

fernet_volume_index=$(kubectl -n "${NAMESPACE}" get deployment "${DEPLOYMENT}" -o json \
  | python3 -c "
import json, sys
d = json.load(sys.stdin)
volumes = d['spec']['template']['spec']['volumes']
for i, v in enumerate(volumes):
    if v['name'] == 'keystone-fernet-keys' and 'secret' in v:
        print(i)
        break
else:
    sys.exit('keystone-fernet-keys Secret volume not found -- has the Deployment structure changed?')
")

patch=$(python3 -c "
import json
idx = ${fernet_volume_index}
patch = [
  {'op': 'replace', 'path': f'/spec/template/spec/volumes/{idx}',
   'value': {'name': 'keystone-fernet-keys', 'emptyDir': {}}},
  {'op': 'add', 'path': '/spec/template/spec/volumes/-',
   'value': {'name': 'keystone-fernet-keys-raw', 'secret': {'secretName': 'keystone-fernet-keys'}}},
  {'op': 'add', 'path': '/spec/template/spec/initContainers/-',
   'value': {
     'name': 'fernet-perms-init',
     'image': 'busybox:1.36',
     'command': ['sh', '-c', 'chown 42424:42424 /etc/keystone/fernet-keys && chmod 700 /etc/keystone/fernet-keys'],
     'securityContext': {
       'runAsUser': 0,
       'runAsNonRoot': False,
       'allowPrivilegeEscalation': False,
       'readOnlyRootFilesystem': True,
       'capabilities': {'add': ['CHOWN', 'FOWNER'], 'drop': ['ALL']},
     },
     'volumeMounts': [{'name': 'keystone-fernet-keys', 'mountPath': '/etc/keystone/fernet-keys'}],
   }},
  {'op': 'add', 'path': '/spec/template/spec/containers/-',
   'value': {
     'name': 'fernet-sync',
     'image': 'busybox:1.36',
     'command': ['sh', '-c',
       'while true; do '
       'for f in /secret-src/*; do n=\$(basename \"\$f\"); '
       'cp \"\$f\" \"/etc/keystone/fernet-keys/\$n.tmp\" && chmod 600 \"/etc/keystone/fernet-keys/\$n.tmp\" && mv \"/etc/keystone/fernet-keys/\$n.tmp\" \"/etc/keystone/fernet-keys/\$n\"; '
       'done; '
       'for f in /etc/keystone/fernet-keys/*; do [ -e \"\$f\" ] || continue; n=\$(basename \"\$f\"); [ -e \"/secret-src/\$n\" ] || rm -f \"\$f\"; done; '
       'sleep 60; done'],
     'securityContext': {
       'runAsUser': 42424,
       'runAsGroup': 42424,
       'allowPrivilegeEscalation': False,
       'readOnlyRootFilesystem': True,
       'capabilities': {'drop': ['ALL']},
     },
     'resources': {'requests': {'cpu': '10m', 'memory': '16Mi'}, 'limits': {'memory': '32Mi'}},
     'volumeMounts': [
       {'name': 'keystone-fernet-keys-raw', 'mountPath': '/secret-src', 'readOnly': True},
       {'name': 'keystone-fernet-keys', 'mountPath': '/etc/keystone/fernet-keys'},
     ],
   }},
]
print(json.dumps(patch))
")

kubectl -n "${NAMESPACE}" patch deployment "${DEPLOYMENT}" --type=json -p="${patch}"
kubectl -n "${NAMESPACE}" rollout status "deployment/${DEPLOYMENT}" --timeout=180s
echo "fernet-perms-init + fernet-sync applied and rolled out successfully."
