#!/usr/bin/env bash
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
JOB=designate-zone-crud

test "$(kubectl -n openstack get deployment designate-api -o jsonpath='{.status.readyReplicas}')" = 2
test "$(kubectl -n openstack get deployment designate-central -o jsonpath='{.status.readyReplicas}')" = 2
test "$(kubectl -n openstack get deployment designate-mdns -o jsonpath='{.status.readyReplicas}')" = 2
test "$(kubectl -n openstack get deployment designate-producer -o jsonpath='{.status.readyReplicas}')" = 2
test "$(kubectl -n openstack get deployment designate-worker -o jsonpath='{.status.readyReplicas}')" = 2
test "$(kubectl -n openstack get deployment powerdns -o jsonpath='{.status.readyReplicas}')" = 2

kubectl delete job "$JOB" --namespace openstack --ignore-not-found
kubectl apply -f "$ROOT/manifests/designate-verify.yaml"
kubectl wait --namespace openstack --for=condition=complete \
  "job/$JOB" --timeout=5m
kubectl logs --namespace openstack "job/$JOB"

test "$(dig +short @192.168.21.9 \
  www.designate-poc.cloud.dcn.ssu.ac.kr A)" = 192.0.2.80
echo "Authoritative DNS lookup through 192.168.21.9 passed."
