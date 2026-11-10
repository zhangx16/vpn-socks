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
GO_BIN=$(command -v go || true)
GO_MINOR=0
if [ -n "$GO_BIN" ];then GO_MINOR=$("$GO_BIN" version | sed -n 's/.*go1\.\([0-9][0-9]*\).*/\1/p');fi
if [ "${GO_MINOR:-0}" -lt 24 ];then
 VERSION=go1.24.7
 case "$(uname -m)" in aarch64|arm64) ARCH=arm64;; x86_64) ARCH=amd64;; *) echo 'Unsupported build architecture' >&2;exit 1;;esac
 FILE="$VERSION.linux-$ARCH.tar.gz"
 curl -fsSL --connect-timeout 10 --max-time 60 'https://go.dev/dl/?mode=json&include=all' -o "$BUILD/go-releases.json"
 HASH=$(python3 - "$BUILD/go-releases.json" "$VERSION" "$FILE" <<'PY'
import json,sys
releases=json.load(open(sys.argv[1]))
print(next(f['sha256'] for r in releases if r['version']==sys.argv[2] for f in r['files'] if f['filename']==sys.argv[3]))
PY
 )
 curl -fsSL --connect-timeout 10 --max-time 180 "https://dl.google.com/go/$FILE" -o "$BUILD/go.tgz"
 printf '%s  %s\n' "$HASH" "$BUILD/go.tgz" | sha256sum -c -
 tar -xzf "$BUILD/go.tgz" -C "$BUILD"
 GO_BIN="$BUILD/go/bin/go"
fi
cd "$BUILD/fanout-$REV"
patch -p1 < "$ROOT/patches/fanout-catalog-source.patch"
patch -p1 < "$ROOT/patches/fanout-fail-closed.patch"
GOMAXPROCS=2 GOMEMLIMIT=128MiB CGO_ENABLED=0 "$GO_BIN" build -p 1 -trimpath -ldflags '-s -w' -o "$BUILD/fanout" .
[ ! -f "$TARGET" ] || cp -p "$TARGET" "$TARGET.before-pool"
install -m 755 "$BUILD/fanout" "$TARGET"
echo 'fanout built with configurable primary catalog support'
