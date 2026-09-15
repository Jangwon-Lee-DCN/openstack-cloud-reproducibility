#!/usr/bin/env bash
set -euo pipefail

test "$(kubectl -n kube-system get deployment metrics-server -o jsonpath='{.spec.replicas}')" = 2
kubectl -n kube-system get deployment metrics-server -o json |
  python3 -c 'import json,sys; d=json.load(sys.stdin); image=d["spec"]["template"]["spec"]["containers"][0]["image"]; assert image.endswith("@sha256:89258156d0e9af60403eafd44da9676fd66f600c7934d468ccc17e42b199aee2"), image'
test "$(kubectl get apiservice v1beta1.metrics.k8s.io -o jsonpath='{.status.conditions[?(@.type=="Available")].status}')" = True
kubectl get --raw /apis/metrics.k8s.io/v1beta1/nodes |
  python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["kind"] == "NodeMetricsList"; assert d["items"]'
