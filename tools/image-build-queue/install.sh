#!/usr/bin/env bash
set -euo pipefail

root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
version=v4.0.4
build_user=${DCN_IMAGE_BUILD_USER:-ubuntu}
build_group=${DCN_IMAGE_BUILD_GROUP:-$(id -gn "$build_user")}
build_home=$(getent passwd "$build_user" | cut -d: -f6)
[[ -n "$build_home" ]] || { echo "cannot resolve home for $build_user" >&2; exit 1; }
build_python=${DCN_IMAGE_BUILD_PYTHON:-$build_home/openstack-production-datacenter/.venv/bin/python}
[[ -x "$build_python" ]] || { echo "image build Python is not executable: $build_python" >&2; exit 1; }
"$build_python" -c 'import build' || {
  echo "image build Python does not provide the required build module: $build_python" >&2
  exit 1
}
case $(uname -m) in
  x86_64) target=x86_64-unknown-linux-musl ;;
  aarch64|arm64) target=aarch64-unknown-linux-musl ;;
  *) echo "unsupported architecture: $(uname -m)" >&2; exit 2 ;;
esac

for command in curl install sha256sum systemctl; do
  command -v "$command" >/dev/null || { echo "missing command: $command" >&2; exit 1; }
done
[[ $(id -u) -eq 0 ]] || { echo "install.sh must run as root" >&2; exit 1; }

stage=$(mktemp -d /tmp/dcn-image-build-queue-install.XXXXXX)
cleanup() { find "$stage" -type f -delete; find "$stage" -depth -type d -empty -delete; }
trap cleanup EXIT
for binary in pueue pueued; do
  asset="$binary-$target"
  curl --fail --location --silent --show-error \
    "https://github.com/Nukesor/pueue/releases/download/$version/$asset" \
    --output "$stage/$asset"
  expected=$(awk -v asset="$asset" '$2==asset {print $1}' "$root/pueue-v4.0.4.sha256")
  [[ -n "$expected" ]] || { echo "missing checksum for $asset" >&2; exit 1; }
  printf '%s  %s\n' "$expected" "$stage/$asset" | sha256sum --check --status || {
    echo "checksum mismatch for $asset" >&2; exit 1;
  }
done

install -d -m 0755 /usr/local/libexec/dcn-image-build-queue /etc/dcn-image-build-queue
install -d -o "$build_user" -g "$build_group" -m 0770 /var/lib/dcn-image-build-queue
install -m 0755 "$stage/pueue-$target" /usr/local/libexec/dcn-image-build-queue/pueue
install -m 0755 "$stage/pueued-$target" /usr/local/libexec/dcn-image-build-queue/pueued
install -m 0755 "$root/dcn_image_build.py" /usr/local/libexec/dcn-image-build-queue/dcn-image-build
install -m 0755 "$root/run_image_build.py" /usr/local/libexec/dcn-image-build-queue/run-image-build
install -m 0755 "$root/init-groups" /usr/local/libexec/dcn-image-build-queue/init-groups
install -m 0644 "$root/pueue.yml" /etc/dcn-image-build-queue/pueue.yml
printf '%s\n' "$build_python" >"$stage/build-python"
install -m 0644 "$stage/build-python" /etc/dcn-image-build-queue/build-python
sed -e "s#@BUILD_USER@#$build_user#g" -e "s#@BUILD_GROUP@#$build_group#g" \
  -e "s#@BUILD_HOME@#$build_home#g" -e "s#@BUILD_PYTHON@#$build_python#g" \
  "$root/dcn-image-build-queue.service" >"$stage/dcn-image-build-queue.service"
install -m 0644 "$stage/dcn-image-build-queue.service" /etc/systemd/system/dcn-image-build-queue.service
ln -sfn /usr/local/libexec/dcn-image-build-queue/dcn-image-build /usr/local/bin/dcn-image-build

systemctl daemon-reload
systemctl enable dcn-image-build-queue.service
systemctl restart dcn-image-build-queue.service
systemctl is-active --quiet dcn-image-build-queue.service
/usr/local/bin/dcn-image-build health
