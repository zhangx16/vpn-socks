#!/bin/sh
# Read-only checks before any package installation or network mutation.
set -eu
reject() { printf '%s\n' "$1" >&2; exit 42; }
for binary in "$(command -v openvpn 2>/dev/null || true)" /usr/local/sbin/openvpn /usr/local/bin/openvpn /usr/sbin/openvpn /sbin/openvpn;do
 [ -n "$binary" ] && [ -f "$binary" ] || continue
 # Match explicit operator policy text only; never try to replace such wrappers.
 if head -c 8192 "$binary" | grep -Eq '严禁运行|禁止运行.*(OpenVPN|openvpn)|OpenVPN.*(prohibited|forbidden|disabled by|not permitted)';then
  reject '服务器预置策略明确禁止 OpenVPN，无法部署当前 VPN 出口方案；请使用允许 OpenVPN 的服务器。未尝试解除限制。'
 fi
done
[ -c /dev/net/tun ] || reject '服务器未开放 /dev/net/tun，无法建立 VPN 出口；请由服务器提供方开放 TUN。'
