#!/usr/bin/env bash
set -euo pipefail

STACK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
JOB=openstack-vm-internal-catalog-reconcile

kubectl -n openstack delete job "${JOB}" --ignore-not-found
kubectl apply -f "${STACK_DIR}/manifests/catalog-reconcile.yaml"
kubectl -n openstack wait --for=condition=Complete "job/${JOB}" --timeout=5m
kubectl -n openstack logs "job/${JOB}"
