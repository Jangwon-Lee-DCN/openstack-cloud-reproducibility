#!/usr/bin/env bash
set -euo pipefail

if [[ "${APPROVE_TAG_CHANGE:-}" != "yes" ]]; then
  echo "Refusing to change Neutron tags. Review the drift report and set APPROVE_TAG_CHANGE=yes." >&2
  exit 2
fi
if [[ $# -ne 3 ]]; then
  echo "usage: APPROVE_TAG_CHANGE=yes $0 <security-group|floating-ip|router> <neutron-id> <cr-uid>" >&2
  exit 2
fi

resource=$1
neutron_id=$2
cr_uid=$3
case "$resource" in
  security-group) command=(security group set) ;;
  floating-ip) command=(floating ip set) ;;
  router) command=(router set) ;;
  *) echo "unsupported resource type" >&2; exit 2 ;;
esac

openstack "${command[@]}" --tag vpc-control-plane --tag "vpc-cr-uid=$cr_uid" "$neutron_id"
