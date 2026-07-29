#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
JOB=barbican-secret-crud

test "$(kubectl -n openstack get deployment barbican-api -o jsonpath='{.status.readyReplicas}')" = 2
test "$(kubectl -n openstack get pdb barbican-api -o jsonpath='{.spec.minAvailable}')" = 1
kubectl -n openstack delete job "${JOB}" --ignore-not-found
kubectl apply -f "${ROOT}/manifests/barbican-verify.yaml"
kubectl -n openstack wait --for=condition=Complete "job/${JOB}" --timeout=5m
kubectl -n openstack logs "job/${JOB}"
