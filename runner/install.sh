#!/bin/sh
# Configure a private job runner behind the existing node's public TLS port.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
HOST=$1
PORT=${2:-35001}
python3 -c 'import re,sys;assert re.fullmatch(r"[a-z0-9.-]+",sys.argv[1]);assert 1<=int(sys.argv[2])<=65535' "$HOST" "$PORT"
test -s /etc/vpn-runner.json
apk add --no-cache nginx py3-paramiko nodejs >/dev/null
CERT=$(jq -r --argjson port "$PORT" '.inbounds[]|select(.port==$port)|.tls.cert_file' /var/lib/fanout/native.json)
KEY=$(jq -r --argjson port "$PORT" '.inbounds[]|select(.port==$port)|.tls.key_file' /var/lib/fanout/native.json)
NODE_HOST=$(jq -r --argjson port "$PORT" '.inbounds[]|select(.port==$port)|.tls.server_name' /var/lib/fanout/native.json)
test -s "$CERT";test -s "$KEY"
mkdir -p /etc/nginx/http.d /var/lib/vpn-runner
chmod 700 /var/lib/vpn-runner
cat > /etc/nginx/http.d/vpn-runner.conf <<EOF
server {
 listen 35012 ssl default_server;
 server_name $NODE_HOST;
 ssl_certificate $CERT;
 ssl_certificate_key $KEY;
 location / {
  proxy_pass https://127.0.0.1:$PORT;
  proxy_http_version 1.1;
  proxy_ssl_verify off;
  proxy_ssl_server_name on;
  proxy_ssl_name $NODE_HOST;
  proxy_set_header Host \$host;
  proxy_set_header Upgrade \$http_upgrade;
  proxy_set_header Connection "upgrade";
  proxy_read_timeout 3600s;
 }
}
server {
 listen 35012 ssl;
 server_name $HOST;
 ssl_certificate $CERT;
 ssl_certificate_key $KEY;
 client_max_body_size 64k;
 location / {
  proxy_pass http://127.0.0.1:35013;
  proxy_set_header Host \$host;
  proxy_http_version 1.1;
  proxy_read_timeout 40s;
 }
}
EOF
cat > /etc/init.d/vpn-runner <<EOF
#!/sbin/openrc-run
name="vpn-runner"
command="/usr/bin/python3"
command_args="$ROOT/runner/service.py"
command_background=true
pidfile="/run/vpn-runner.pid"
supervisor=supervise-daemon
respawn_delay=5
respawn_max=0
output_log="/var/log/vpn-runner.log"
error_log="/var/log/vpn-runner.log"
export VPN_RUNNER_PROJECT="$ROOT"
depend() { need net; }
EOF
cat > /etc/init.d/vpn-runner-proxy <<EOF
#!/sbin/openrc-run
name="vpn-runner-proxy"
depend() { need net nginx vpn-runner; }
start() {
 iptables -t nat -C PREROUTING -i eth0 -p tcp --dport $PORT -m comment --comment vpn-runner-proxy -j REDIRECT --to-ports 35012 2>/dev/null || iptables -t nat -I PREROUTING 1 -i eth0 -p tcp --dport $PORT -m comment --comment vpn-runner-proxy -j REDIRECT --to-ports 35012
}
stop() { iptables -t nat -D PREROUTING -i eth0 -p tcp --dport $PORT -m comment --comment vpn-runner-proxy -j REDIRECT --to-ports 35012 2>/dev/null || true; }
EOF
chmod 755 /etc/init.d/vpn-runner /etc/init.d/vpn-runner-proxy
nginx -t
rc-service nginx status >/dev/null 2>&1 && rc-service nginx reload || rc-service nginx start
rc-service vpn-runner status >/dev/null 2>&1 && rc-service vpn-runner restart || rc-service vpn-runner start
rc-service vpn-runner-proxy start
for service in nginx vpn-runner vpn-runner-proxy;do rc-update add "$service" default;done
echo 'Private SSH runner installed; existing node traffic is forwarded to its original Xray listener.'
