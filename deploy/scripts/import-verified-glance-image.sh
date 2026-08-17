#!/usr/bin/env bash
set -euo pipefail

name=${IMAGE_NAME:?set IMAGE_NAME}
url=${IMAGE_URL:?set IMAGE_URL}
sha256=${IMAGE_SHA256:?set IMAGE_SHA256}
sbom=${IMAGE_SBOM:?set IMAGE_SBOM to a CycloneDX JSON file}
scan=${IMAGE_VULNERABILITY_REPORT:?set IMAGE_VULNERABILITY_REPORT}
[[ $url == https://* ]] || { echo 'IMAGE_URL must use HTTPS' >&2; exit 2; }
[[ $sha256 =~ ^[0-9a-f]{64}$ ]] || { echo 'IMAGE_SHA256 must be lowercase SHA-256' >&2; exit 2; }
root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
path="$work/image.qcow2"
curl --fail --location --retry 5 --output "$path" "$url"
echo "$sha256  $path" | sha256sum --check -
qemu-img check "$path"
python3 "$root/deploy/scripts/verify_image_supply_chain.py" "$sbom" "$scan"
existing=$(openstack image list --name "$name" --status active -f value -c ID)
[[ -z $existing ]] || { echo "$name already exists; lifecycle replacement must be explicit" >&2; exit 1; }
openstack image create "$name" --file "$path" --disk-format qcow2 --container-format bare \
  --property os_distro=ubuntu --property source_sha256="$sha256" \
  --property dcn_supply_chain_verified=true --private --protected
