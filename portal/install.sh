#!/bin/sh
# Debian/Ubuntu self-hosted console; configure HTTPS nginx separately.
set -eu
PROJECT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
test "$(id -u)" = 0
test -s /etc/vpn-control.json
test -s /etc/vpn-runner.json
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-venv nginx nodejs
python3 -m venv /opt/vpn-control/venv
/opt/vpn-control/venv/bin/pip install -r "$PROJECT/runner/requirements.txt"
install -d -m 700 /var/lib/vpn-runner /var/lib/vpn-control
for service in vpn-control vpn-runner;do
 if [ "$service" = vpn-control ];then SCRIPT=portal/server.py;else SCRIPT=runner/service.py;fi
 cat > "/etc/systemd/system/$service.service" <<EOF
[Unit]
Description=$service
After=network-online.target
Wants=network-online.target
[Service]
WorkingDirectory=$PROJECT
Environment=VPN_RUNNER_PROJECT=$PROJECT
Environment=VPN_POOL_DIR=/var/lib/vpn-runner/pool
ExecStart=/opt/vpn-control/venv/bin/python $PROJECT/$SCRIPT
Restart=always
RestartSec=5
UMask=0077
[Install]
WantedBy=multi-user.target
EOF
done
systemctl daemon-reload
systemctl enable --now vpn-control vpn-runner
printf '%s\n' 'Console is on 127.0.0.1:35015. Configure an HTTPS virtual host for your domain; forward Host and X-Real-IP. Executor is loopback-only on 35013.'
