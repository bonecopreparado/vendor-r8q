#!/usr/bin/env bash
# Build the modern compiler and checker against the same pinned static library.
set -euo pipefail
project_root="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$project_root"
upstream_commit=6423998bc7b154da7f9fe726cfda9ace774dfa94
mkdir -p .deps build
git init .deps/selinux
git -C .deps/selinux remote add origin https://github.com/SELinuxProject/selinux.git
git -C .deps/selinux fetch --depth=1 origin "$upstream_commit"
git -C .deps/selinux checkout --detach FETCH_HEAD
test "$(git -C .deps/selinux rev-parse HEAD)" = "$upstream_commit"
make -C .deps/selinux/libsepol/src -j2 libsepol.a
cc -D_GNU_SOURCE -I.deps/selinux/libsepol/include -I.deps/selinux/libsepol/cil/include \
    .deps/selinux/secilc/secilc.c .deps/selinux/libsepol/src/libsepol.a -o build/secilc-host
printf '%s  %s\n' e2f1f72e28e3f55ea0ce896a98b4b48e017dbf74c385538e9fb4f3484b6b2524 ci-r8q/inputs/selinux-policy-audit-bundle.tar.gz | sha256sum -c -
tar -xzf ci-r8q/inputs/selinux-policy-audit-bundle.tar.gz -C .deps
cc -I.deps/selinux/libsepol/include .deps/policy-bundle/check_policy_caps.c \
    .deps/selinux/libsepol/src/libsepol.a -o build/check-policy-caps
sha256sum build/secilc-host build/check-policy-caps > build/compiler-sha256.txt
printf '%s\n' "$upstream_commit" > build/selinux-source-commit.txt
