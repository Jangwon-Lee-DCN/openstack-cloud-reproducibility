#!/usr/bin/env bash
set -euo pipefail

NAMESPACE=${NAMESPACE:-openstack}
JOB=project-facade-keystone-reconcile
IMAGE=$(kubectl -n "$NAMESPACE" get deployment project-facade \
  -o jsonpath='{.spec.template.spec.containers[?(@.name=="project-facade")].image}')
[[ -n "$IMAGE" ]] || { echo "project-facade image could not be resolved" >&2; exit 1; }

kubectl -n "$NAMESPACE" delete job "$JOB" --ignore-not-found --wait=true
kubectl apply -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: $JOB
  namespace: $NAMESPACE
spec:
  backoffLimit: 0
  ttlSecondsAfterFinished: 86400
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: reconcile
          image: $IMAGE
          command: [python3, -c]
          args:
            - |
              import os
              import requests

              url = os.environ["ADMIN_AUTH_URL"].rstrip("/")
              admin_auth = {"auth": {
                  "identity": {"methods": ["password"], "password": {"user": {
                      "name": os.environ["ADMIN_USERNAME"],
                      "password": os.environ["ADMIN_PASSWORD"],
                      "domain": {"name": os.environ["ADMIN_USER_DOMAIN"]},
                  }}},
                  "scope": {"project": {
                      "name": os.environ["ADMIN_PROJECT"],
                      "domain": {"name": os.environ["ADMIN_PROJECT_DOMAIN"]},
                  }},
              }}
              response = requests.post(url + "/auth/tokens", json=admin_auth, timeout=15)
              response.raise_for_status()
              headers = {"X-Auth-Token": response.headers["X-Subject-Token"]}

              response = requests.get(url + "/domains", headers=headers,
                                      params={"name": os.environ["PF_USER_DOMAIN"]}, timeout=15)
              response.raise_for_status()
              domains = response.json()["domains"]
              if len(domains) != 1:
                  raise RuntimeError("project-facade user domain was not uniquely resolved")
              response = requests.get(url + "/users", headers=headers, params={
                  "name": os.environ["PF_USERNAME"], "domain_id": domains[0]["id"],
              }, timeout=15)
              response.raise_for_status()
              users = response.json()["users"]
              if len(users) > 1:
                  raise RuntimeError("project-facade service user was not uniquely resolved")
              if users:
                  user_id = users[0]["id"]
                  response = requests.patch(url + "/users/" + user_id, headers=headers,
                                            json={"user": {"password": os.environ["PF_PASSWORD"],
                                                           "enabled": True}}, timeout=15)
              else:
                  response = requests.post(url + "/users", headers=headers, json={"user": {
                      "name": os.environ["PF_USERNAME"], "password": os.environ["PF_PASSWORD"],
                      "domain_id": domains[0]["id"], "enabled": True,
                      "description": "Service identity for project-facade",
                  }}, timeout=15)
              response.raise_for_status()
              user_id = response.json()["user"]["id"]

              response = requests.get(url + "/domains", headers=headers,
                                      params={"name": os.environ["PF_DOMAIN"]}, timeout=15)
              response.raise_for_status()
              target_domains = response.json()["domains"]
              if len(target_domains) != 1:
                  raise RuntimeError("project-facade target domain was not uniquely resolved")
              response = requests.get(url + "/roles", headers=headers,
                                      params={"name": "admin"}, timeout=15)
              response.raise_for_status()
              roles = response.json()["roles"]
              if len(roles) != 1:
                  raise RuntimeError("admin role was not uniquely resolved")
              response = requests.put(
                  url + "/domains/" + target_domains[0]["id"] + "/users/" + user_id
                  + "/roles/" + roles[0]["id"], headers=headers, timeout=15,
              )
              response.raise_for_status()

              service_auth = {"auth": {
                  "identity": {"methods": ["password"], "password": {"user": {
                      "name": os.environ["PF_USERNAME"],
                      "password": os.environ["PF_PASSWORD"],
                      "domain": {"name": os.environ["PF_USER_DOMAIN"]},
                  }}},
                  "scope": {"domain": {"name": os.environ["PF_DOMAIN"]}},
              }}
              response = requests.post(url + "/auth/tokens", json=service_auth, timeout=15)
              response.raise_for_status()
              print("project-facade Keystone credential reconciled and verified")
          env:
            - {name: ADMIN_AUTH_URL, valueFrom: {secretKeyRef: {name: keystone-keystone-admin, key: OS_AUTH_URL}}}
            - {name: ADMIN_USERNAME, valueFrom: {secretKeyRef: {name: keystone-keystone-admin, key: OS_USERNAME}}}
            - {name: ADMIN_PASSWORD, valueFrom: {secretKeyRef: {name: keystone-keystone-admin, key: OS_PASSWORD}}}
            - {name: ADMIN_USER_DOMAIN, valueFrom: {secretKeyRef: {name: keystone-keystone-admin, key: OS_USER_DOMAIN_NAME}}}
            - {name: ADMIN_PROJECT, valueFrom: {secretKeyRef: {name: keystone-keystone-admin, key: OS_PROJECT_NAME}}}
            - {name: ADMIN_PROJECT_DOMAIN, valueFrom: {secretKeyRef: {name: keystone-keystone-admin, key: OS_PROJECT_DOMAIN_NAME}}}
            - {name: PF_USERNAME, valueFrom: {secretKeyRef: {name: project-facade-keystone, key: OS_USERNAME}}}
            - {name: PF_PASSWORD, valueFrom: {secretKeyRef: {name: project-facade-keystone, key: OS_PASSWORD}}}
            - {name: PF_USER_DOMAIN, valueFrom: {secretKeyRef: {name: project-facade-keystone, key: OS_USER_DOMAIN_NAME}}}
            - {name: PF_DOMAIN, valueFrom: {secretKeyRef: {name: project-facade-keystone, key: OS_DOMAIN_NAME}}}
EOF
kubectl -n "$NAMESPACE" wait --for=condition=complete "job/$JOB" --timeout=5m || {
  kubectl -n "$NAMESPACE" logs "job/$JOB" --tail=100 >&2 || true
  exit 1
}
kubectl -n "$NAMESPACE" logs "job/$JOB" --tail=10
