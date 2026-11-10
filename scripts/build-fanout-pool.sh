#!/bin/sh
# Small, auditable upstream patch: make the primary CSV URL configurable.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
TARGET=${1:-/usr/local/bin/fanout}
REV=d7ce5224caf3469b19876982abdf8d1be16c4a8b
BUILD=$(mktemp -d)
trap 'rm -rf "$BUILD"' EXIT
curl -fsSL --connect-timeout 10 --max-time 90 "https://codeload.github.com/byJoey/fanout/tar.gz/$REV" -o "$BUILD/source.tgz"
tar -xzf "$BUILD/source.tgz" -C "$BUILD"
cd "$BUILD/fanout-$REV"
patch -p1 < "$ROOT/patches/fanout-catalog-source.patch"
CGO_ENABLED=0 go build -trimpath -ldflags '-s -w' -o "$BUILD/fanout" .
[ ! -f "$TARGET" ] || cp -p "$TARGET" "$TARGET.before-pool"
install -m 755 "$BUILD/fanout" "$TARGET"
echo 'fanout built with configurable primary catalog support'
