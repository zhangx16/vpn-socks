#!/bin/sh
set -eu
umask 077
JOB=$1
emit() { printf '{"step":"%s","state":"%s","message":"%s"}\n' "$1" "$2" "$3"; }
LOG_FILE="$JOB/packages.log"
PHASE='检查系统依赖'
failed() {
 code=$?
 [ "$code" -eq 0 ] && return
 printf '{"step":"install","state":"error","message":"%s失败；退出码 %s，日志 %s"}\n' "$PHASE" "$code" "$(basename "$LOG_FILE")"
 # Runner redacts credentials and selects a bounded tail before showing details.
 if [ -s "$LOG_FILE" ];then grep -Ei 'error|failed|not found|unable|denied|错误|失败|cannot|禁止|严禁|No space|temporary failure' "$LOG_FILE" | tail -n 8 >&2 || true;fi
}
trap failed EXIT
emit install running '检查系统依赖和网络命名空间'
sh "$JOB/vpn-socks/scripts/preflight.sh"
. /etc/os-release
case "$ID" in
 alpine) apk add --no-cache bash curl jq python3 iproute2 iptables openvpn util-linux openssl unzip ca-certificates logrotate nginx > "$JOB/packages.log" 2>&1 ;;
 debian|ubuntu) apt-get update -qq > "$JOB/packages.log" 2>&1; DEBIAN_FRONTEND=noninteractive apt-get install -y -qq bash curl jq python3 iproute2 iptables openvpn util-linux openssl unzip ca-certificates logrotate nginx >> "$JOB/packages.log" 2>&1 ;;
 *) emit install error '此发行版暂不支持自动部署'; exit 1 ;;
esac
test -c /dev/net/tun || { emit install error '服务器未开放 TUN 设备'; exit 1; }
CHECK="vp_$(basename "$JOB" | cut -c1-8)"
PHASE='创建网络命名空间'
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
open('/var/lib/fanout/settings.json','w').write(json.dumps({'port':port,'listen_addr':'127.0.0.1','residential_only':False}))
PY
fi
if [ ! -x /usr/local/bin/fanout ] || [ ! -x /var/lib/fanout/bin/xray ]; then
 emit install running '安装 fanout 和 Xray，安装日志不在网页回显'
 PHASE='安装 fanout 和 Xray'
 LOG_FILE="$JOB/fanout-install.log"
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
emit install running '汇总官方主站和镜像出口库'
PHASE='初始化汇总出口池'
LOG_FILE="$JOB/pool-install.log"
sh "$JOB/vpn-socks/scripts/install-pool.sh" > "$JOB/pool-install.log" 2>&1
if command -v rc-service >/dev/null;then rc-service fanout restart >> "$JOB/pool-install.log" 2>&1
else systemctl restart fanout;fi
python3 "$JOB/vpn-socks/scripts/provision.py" "$JOB/request.json" "$JOB/vpn-socks"
trap - EXIT
