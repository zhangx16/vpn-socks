#!/bin/sh
set -eu
umask 077
JOB=$1
emit() { printf '{"step":"%s","state":"%s","message":"%s"}\n' "$1" "$2" "$3"; }
trap 'emit install error "服务器安装步骤失败，私有安装日志保存在任务目录"' EXIT
emit install running '检查系统依赖和网络命名空间'
. /etc/os-release
case "$ID" in
 alpine) apk add --no-cache bash curl jq python3 iproute2 iptables openvpn util-linux openssl unzip ca-certificates logrotate > "$JOB/packages.log" 2>&1 ;;
 debian|ubuntu) apt-get update -qq > "$JOB/packages.log" 2>&1; DEBIAN_FRONTEND=noninteractive apt-get install -y -qq bash curl jq python3 iproute2 iptables openvpn util-linux openssl unzip ca-certificates logrotate >> "$JOB/packages.log" 2>&1 ;;
 *) emit install error '此发行版暂不支持自动部署'; exit 1 ;;
esac
test -c /dev/net/tun || { emit install error '服务器未开放 TUN 设备'; exit 1; }
CHECK="vp_$(basename "$JOB" | cut -c1-8)"
ip netns add "$CHECK"
ip netns del "$CHECK"
mkdir -p /var/lib/fanout
chmod 700 /var/lib/fanout
if [ ! -s /var/lib/fanout/settings.json ]; then
 python3 - <<'PY'
import json,socket
for port in range(33011,33101):
 try:
  s=socket.socket();s.bind(('127.0.0.1',port));s.close();break
 except OSError:continue
else:raise SystemExit('No free management port')
open('/var/lib/fanout/settings.json','w').write(json.dumps({'port':port,'listen_addr':'127.0.0.1','residential_only':True}))
PY
fi
if [ ! -x /usr/local/bin/fanout ] || [ ! -x /var/lib/fanout/bin/xray ]; then
 emit install running '安装 fanout 和 Xray，安装日志不在网页回显'
 curl -fsSL --connect-timeout 10 --max-time 60 https://raw.githubusercontent.com/byJoey/fanout/main/install.sh -o "$JOB/fanout-install.sh"
 (cd "$JOB" && bash fanout-install.sh > "$JOB/fanout-install.log" 2>&1)
fi
mkdir -p /usr/local/libexec/fanout
install -m 755 "$JOB/vpn-socks/libexec/ip-netns-compat" /usr/local/libexec/fanout/ip
if command -v rc-service >/dev/null; then
 mkdir -p /etc/conf.d; touch /etc/conf.d/fanout
 if ! grep -q '/usr/local/libexec/fanout' /etc/conf.d/fanout; then
  printf '\n%s\n' 'export PATH="/usr/local/libexec/fanout:$PATH"' >> /etc/conf.d/fanout
  rc-service fanout restart > "$JOB/service.log" 2>&1
 fi
else
 mkdir -p /etc/systemd/system/fanout.service.d
 printf '[Service]\nEnvironment="PATH=/usr/local/libexec/fanout:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"\n' > /etc/systemd/system/fanout.service.d/netns.conf
 systemctl daemon-reload; systemctl restart fanout
fi
emit install done 'fanout 与 Xray 已就绪'
python3 "$JOB/vpn-socks/scripts/provision.py" "$JOB/request.json" "$JOB/vpn-socks"
trap - EXIT
