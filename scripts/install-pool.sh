#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
mkdir -p /usr/local/libexec/fanout
for file in catalog_pool.py pool_server.py;do install -m 755 "$ROOT/libexec/$file" "/usr/local/libexec/fanout/$file";done
if ! grep -aq FANOUT_VPNGATE_SOURCE /usr/local/bin/fanout;then
 if ! command -v patch >/dev/null;then
  if command -v apk >/dev/null;then apk add --no-cache patch
  else apt-get install -y -qq patch;fi
 fi
 sh "$ROOT/scripts/build-fanout-pool.sh"
fi
if command -v rc-service >/dev/null;then
 install -m 755 "$ROOT/openrc/fanout-pool" /etc/init.d/fanout-pool
 mkdir -p /etc/conf.d;touch /etc/conf.d/fanout
 if ! grep -q FANOUT_VPNGATE_SOURCE /etc/conf.d/fanout;then printf '\n%s\n' 'export FANOUT_VPNGATE_SOURCE="http://127.0.0.1:35014/catalog.csv"' >> /etc/conf.d/fanout;fi
 rc-update add fanout-pool default
 rc-service fanout-pool status >/dev/null 2>&1 || rc-service fanout-pool start
else
 install -m 644 "$ROOT/systemd/fanout-pool.service" /etc/systemd/system/fanout-pool.service
 mkdir -p /etc/systemd/system/fanout.service.d
 printf '[Unit]\nWants=fanout-pool.service\nAfter=fanout-pool.service\n[Service]\nEnvironment="FANOUT_VPNGATE_SOURCE=http://127.0.0.1:35014/catalog.csv"\n' > /etc/systemd/system/fanout.service.d/pool.conf
 systemctl daemon-reload;systemctl enable --now fanout-pool
fi
python3 /usr/local/libexec/fanout/catalog_pool.py
