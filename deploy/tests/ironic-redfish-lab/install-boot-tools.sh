#!/usr/bin/env bash
set -euo pipefail

remote_host="${1:-cloud-controller-1}"
target=/var/lib/ironic/boot-tools

sudo apt-get update
sudo apt-get install -y \
  genisoimage=9:1.1.11-3.5 \
  isolinux=3:6.04~git20190206.bf6db5b4+dfsg1-3ubuntu3 \
  syslinux-common=3:6.04~git20190206.bf6db5b4+dfsg1-3ubuntu3 \
  libmagic1t64=1:5.45-3build1

libmagic=$(ldconfig -p | awk '/libmagic.so.1 \(/ {print $NF; exit}')
test -n "$libmagic"

sudo install -d -m 0755 "$target"
sudo install -m 0755 /usr/bin/genisoimage "$target/mkisofs"
sudo install -m 0644 "$libmagic" "$target/libmagic.so.1"
sudo install -m 0644 /usr/share/misc/magic.mgc "$target/magic.mgc"
sudo install -m 0644 /usr/lib/ISOLINUX/isolinux.bin "$target/isolinux.bin"
sudo install -m 0644 /usr/lib/syslinux/modules/bios/ldlinux.c32 \
  "$target/ldlinux.c32"

check_hashes() {
  local prefix=$1
  test "$(sha256sum "$prefix/mkisofs" | awk '{print $1}')" = \
    9bacc5951ca0767701cfd8e6b47537f199977e51a6e943f4edfdcf9d639d99d2
  test "$(sha256sum "$prefix/libmagic.so.1" | awk '{print $1}')" = \
    2f4745657a648f09add1aee122891f9be1c24bae93d29e734da9386544fedb71
  test "$(sha256sum "$prefix/magic.mgc" | awk '{print $1}')" = \
    72a25195a2623fe160e926bf20952b6b74b29d6c91e0174a5fa062f02beee1aa
  test "$(sha256sum "$prefix/isolinux.bin" | awk '{print $1}')" = \
    f0f645e52bbe18bf7a4ac07be9afa985e21d8eb8c9c57938bdaf5b868a0e0e7f
  test "$(sha256sum "$prefix/ldlinux.c32" | awk '{print $1}')" = \
    714faf7d286cd9d47c045c9e8dc614b509b1babc3bb39c095922974a0a62dddf
}
check_hashes "$target"

archive=$(mktemp)
trap 'rm -f "$archive"' EXIT
sudo tar -C "$target" -cf "$archive" \
  mkisofs libmagic.so.1 magic.mgc isolinux.bin ldlinux.c32
scp "$archive" "$remote_host:/tmp/ironic-boot-tools.tar"
ssh "$remote_host" "
  sudo install -d -m 0755 '$target'
  sudo tar -C '$target' -xf /tmp/ironic-boot-tools.tar
  sudo chmod 0755 '$target/mkisofs'
  sudo chmod 0644 '$target/libmagic.so.1' '$target/magic.mgc' \
    '$target/isolinux.bin' '$target/ldlinux.c32'
  rm -f /tmp/ironic-boot-tools.tar
"

sha256sum "$target"/{mkisofs,libmagic.so.1,magic.mgc,isolinux.bin,ldlinux.c32}
ssh "$remote_host" \
  "sha256sum '$target'/{mkisofs,libmagic.so.1,magic.mgc,isolinux.bin,ldlinux.c32}"
