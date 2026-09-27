#!/usr/bin/env bash
# End-to-end test of a delta upgrade, on an x86_64 or aarch64 dev machine.
#
#   nixos/tests/delta-e2e/run.sh <base-toplevel> <target-toplevel>
#
# Downloads the base system into a separate test store, then runs the real
# upgrade steps (dry run, delta prefetch against the live differ, nix build
# with the staged cache) in bwrap with that store at /nix. Nothing from the
# systems is executed, so an aarch64 system works on x86_64. Your own
# /nix/store is not changed. The test store lives in $DELTA_E2E_DIR
# (default /tmp/pifinder-delta-e2e) and is reused between runs.
set -euo pipefail
base=$1 target=$2
here=$(cd "$(dirname "$0")" && pwd)
dir=${DELTA_E2E_DIR:-/tmp/pifinder-delta-e2e}
mkdir -p "$dir"
cd "$dir"

subs="https://cache.pifinder.eu/pifinder-release https://cache.pifinder.eu/pifinder https://cache.nixos.org"
keys="cache.nixos.org-1:6NCHdD59X431o0gWypbMrAURkbJ16ZPMQFGspcDShjY= pifinder:8UU/O3oLkaJHHUyqEcPGl+9F1m4MqDca39Ewl49jBmE= pifinder-release:WG/Fw1cIX7YpwfWrbWTP5eCzn3bz6AaicW5qKxLKpoM="

# The base, as the device holds it.
nix build --store "$dir/pstore" "$base" --max-jobs 0 --no-link \
  --option substituters "$subs" --option trusted-public-keys "$keys"
# Everything the target has beyond the base must be missing, as on the device
# before the upgrade (an earlier run may have fetched it).
if nix path-info --store "$dir/pstore" "$target" >/dev/null 2>&1; then
  mapfile -t extra < <(comm -23 \
    <(nix path-info --store "$dir/pstore" -r "$target" | sort) \
    <(nix path-info --store "$dir/pstore" -r "$base" | sort))
  nix store delete --store "$dir/pstore" "${extra[@]}"
fi

# Tools for the sandbox, copied into the test store.
outs=()
for a in python3^out nix^out zstd^bin coreutils^out bash^out cacert^out; do
  outs+=("$(nix build --no-link --print-out-paths "nixpkgs#$a")")
done
nix copy --to "$dir/pstore" "${outs[@]}"
path=$(printf '%s/bin:' "${outs[@]:0:5}"); path=${path%:}
ca="${outs[5]}/etc/ssl/certs/ca-bundle.crt"

# A small /etc of real files: on NixOS these link into /nix/store, which the
# sandbox replaces with the test store.
rm -rf etc; mkdir -p etc home
cat /etc/resolv.conf > etc/resolv.conf
cat /etc/nsswitch.conf > etc/nsswitch.conf
cat /etc/hosts > etc/hosts
getent passwd "$(id -u)" > etc/passwd
getent group "$(id -g)" > etc/group

# Same substituters and keys as the device's nix.conf.
nc="substituters = $subs
trusted-public-keys = $keys
experimental-features = nix-command flakes
require-sigs = true"
bw="$(nix build --no-link --print-out-paths nixpkgs#bubblewrap)/bin/bwrap"
rm -rf work
exec "$bw" --dev-bind / / --bind "$dir/pstore/nix" /nix \
  --ro-bind "$dir/etc" /etc \
  --clearenv --setenv PATH "$path" --setenv HOME "$dir/home" \
  --setenv NIX_REMOTE local --setenv NIX_CONFIG "$nc" --setenv NIX_CONF_DIR /nonexistent \
  --setenv SSL_CERT_FILE "$ca" --setenv NIX_SSL_CERT_FILE "$ca" \
  -- python3 "$here/harness.py" "$target" "$dir/work"
