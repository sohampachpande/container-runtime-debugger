#!/usr/bin/env bash
set -euo pipefail

readonly tetragon_version="v1.7.0"
readonly repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "$(uname -s)" != "Linux" || "$(uname -m)" != "x86_64" ]]; then
  echo "Run this script on the Ubuntu x86_64 VM, not on macOS." >&2
  exit 1
fi

if [[ ! -r /sys/kernel/btf/vmlinux ]]; then
  echo "Readable kernel BTF is required at /sys/kernel/btf/vmlinux." >&2
  exit 1
fi

if [[ "$(stat -fc %T /sys/fs/cgroup)" != "cgroup2fs" ]]; then
  echo "This lab expects cgroup v2." >&2
  exit 1
fi

sudo -v

missing_packages=()
for package in ca-certificates curl git less python3 tar; do
  if [[ "$(dpkg-query -W -f='${Status}' "$package" 2>/dev/null || true)" != "install ok installed" ]]; then
    missing_packages+=("$package")
  fi
done

if (( ${#missing_packages[@]} > 0 )); then
  sudo apt-get update
  sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    "${missing_packages[@]}"
fi

if command -v tetragon >/dev/null 2>&1 || command -v tetra >/dev/null 2>&1; then
  echo "Tetragon or tetra is already installed; leaving binaries, configuration, and service unchanged."
  echo "See docs/tetragon.md to inspect or update the existing deployment."
  exit 0
fi

readonly download_dir="$(mktemp -d)"
trap 'rm -rf "$download_dir"' EXIT
readonly archive="tetragon-${tetragon_version}-amd64.tar.gz"
readonly release_url="https://github.com/cilium/tetragon/releases/download/${tetragon_version}"

cd "$download_dir"
curl --fail --location --remote-name "${release_url}/${archive}"
curl --fail --location --remote-name "${release_url}/${archive}.sha256sum"
sha256sum --check "${archive}.sha256sum"
tar -xzf "$archive"

sudo install -d -m 0755 /etc/tetragon/tetragon.conf.d
sudo install -m 0644 "$repo_root"/collector/tetragon/tetragon.conf.d/* \
  /etc/tetragon/tetragon.conf.d/
sudo install -d -m 0700 /var/log/tetragon

cd "tetragon-${tetragon_version}-amd64"
sudo ./install.sh
tetra version
sudo /usr/local/lib/tetragon/bpftool version
sudo systemctl status tetragon --no-pager --full

echo "Installation finished. Follow docs/tetragon.md to verify sensor loading and a live execution event."
