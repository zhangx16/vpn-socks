#!/bin/sh
# Install the supervisor overlay on an existing Alpine/OpenRC fanout host.
set -eu
umask 077
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DOMAIN=${1:-}
REGION=${2:-JP}
NODE_PORT=${3:-33003}
if [ "$(id -u)" != 0 ]; then echo 'Run as root.' >&2; exit 1; fi
if [ -z "$DOMAIN" ]; then echo "Usage: $0 your-cf-hostname.example [COUNTRY_CODE] [TLS_PORT]" >&2; exit 1; fi
if command -v rc-service >/dev/null && command -v apk >/dev/null; then INIT=openrc
elif command -v systemctl >/dev/null && command -v apt-get >/dev/null; then INIT=systemd
else echo 'Supported: Alpine/OpenRC or Debian/Ubuntu/systemd.' >&2; exit 1
fi
service_stop() { if [ "$INIT" = openrc ]; then rc-service "$1" stop; else systemctl stop "$1"; fi; }
service_start() { if [ "$INIT" = openrc ]; then rc-service "$1" start; else systemctl start "$1"; fi; }
if [ ! -x /var/lib/fanout/bin/xray ] || [ ! -s /var/lib/fanout/native.json ]; then
    echo 'Install upstream fanout and configure native VLESS WS on 33002 and WS TLS on 33003 first; see README.' >&2; exit 1
fi
if [ "$INIT" = openrc ]; then apk add --no-cache bash curl jq python3 iproute2 iptables openvpn util-linux logrotate
else DEBIAN_FRONTEND=noninteractive apt-get install -y -qq bash curl jq python3 iproute2 iptables openvpn util-linux logrotate; fi
mkdir -p /usr/local/sbin /usr/local/libexec/fanout /var/lib/fanout-speed /var/lib/fanout-ha
chmod 700 /var/lib/fanout-speed /var/lib/fanout-ha
if [ "${ALLOW_SINGLE_EXIT:-0}" = 1 ]; then SINGLE=--allow-single; else SINGLE=; fi
python3 "$ROOT/scripts/configure-probes.py" --domain "$DOMAIN" --region "$REGION" --port "$NODE_PORT" $SINGLE
/var/lib/fanout/bin/xray run -test -config /var/lib/fanout-ha/probe.json
# Pause only the overlay services while replacing their scripts.
for service in fanout-speed fanout-ha fanout-probe; do service_stop "$service" >/dev/null 2>&1 || true; done
install -m 755 "$ROOT/bin/fanout-ha" /usr/local/sbin/fanout-ha
install -m 755 "$ROOT/bin/fanout-speed" /usr/local/sbin/fanout-speed
install -m 755 "$ROOT/libexec/scan-jp" /usr/local/libexec/fanout/scan-jp
for file in catalog_pool.py pool_server.py;do install -m 755 "$ROOT/libexec/$file" "/usr/local/libexec/fanout/$file";done
for service in fanout-probe fanout-ha fanout-speed; do
    if [ "$INIT" = openrc ]; then install -m 755 "$ROOT/openrc/$service" "/etc/init.d/$service"
    else install -m 644 "$ROOT/systemd/$service.service" "/etc/systemd/system/$service.service"; fi
done
[ -f /etc/fanout-speed.json ] || install -m 600 "$ROOT/config/fanout-speed.json" /etc/fanout-speed.json
if [ "${FANOUT_LXC_COMPAT:-0}" = 1 ]; then
    install -m 755 "$ROOT/libexec/ip-netns-compat" /usr/local/libexec/fanout/ip
    mkdir -p /etc/conf.d
    touch /etc/conf.d/fanout
    if ! grep -q '/usr/local/libexec/fanout' /etc/conf.d/fanout; then
        printf '\n%s\n' 'export PATH="/usr/local/libexec/fanout:$PATH"' >> /etc/conf.d/fanout
    fi
    if [ "$INIT" = openrc ]; then rc-service fanout restart; else
        mkdir -p /etc/systemd/system/fanout.service.d
        printf '[Service]\nEnvironment="PATH=/usr/local/libexec/fanout:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"\n' > /etc/systemd/system/fanout.service.d/netns.conf
        systemctl daemon-reload; systemctl restart fanout
    fi
fi
# Consolidate the two legacy overlay rotation files to avoid duplicate entries.
rm -f /etc/logrotate.d/fanout-ha /etc/logrotate.d/fanout-speed
cat > /etc/logrotate.d/fanout-optimizer <<'ROTATE'
/var/log/fanout-ha.log /var/log/fanout-probe.log /var/log/fanout-speed.log {
    daily
    maxsize 1M
    rotate 4
    compress
    missingok
    notifempty
    copytruncate
    su root root
}
ROTATE
for service in fanout-probe fanout-ha fanout-speed; do
    if [ "$INIT" = openrc ]; then rc-update add "$service" default; else systemctl daemon-reload; systemctl enable "$service"; fi
    service_start "$service"
done
echo 'Installed. See /etc/fanout-speed.json and /var/lib/fanout-speed/state.json.'
