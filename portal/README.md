# 自托管管理员控制台

控制台运行在自己的 Debian / Ubuntu 服务器，通过 nginx HTTPS 提供访问，不需要 ChatGPT 账户。Python Web 服务监听 `127.0.0.1:35015`，SSH 执行器监听 `127.0.0.1:35013`。两项服务均由 systemd 开机启动、异常重启。

## 安装

1. 下载本项目到固定目录，安装 Python 3。
2. 运行 `sudo python3 portal/setup.py`，按隐藏提示设置域名、管理员账号密码和 Cloudflare Token。
3. 运行 `sudo sh portal/install.sh`。
4. 在 nginx 新建该域名的 HTTPS 虚拟主机，转发到 `http://127.0.0.1:35015`，传递 `Host` 和 `X-Real-IP`，设置 `client_max_body_size 64k`、`proxy_read_timeout 180s`。不要公开执行器的 35013 端口。
5. 配置域名橙云 DNS、回源端口 443、该主机名的 Full (strict) TLS 以及有效的源站证书。HTTP 80 可仅开放 ACME 证书续期和 HTTPS 跳转。

配置位于 `/etc/vpn-control.json` 和 `/etc/vpn-runner.json`，权限 0600。管理员密码采用 PBKDF2-SHA256（600000 次）加盐存储；会话仅保存随机令牌的 SHA256，12 小时到期。Cookie 启用 Secure、HttpOnly 和 SameSite=Strict。所有 POST 检查 Origin；登录失败按地址限速。网页可修改管理员密码，修改后撤销所有会话。

SSH 密码、私钥和任务传入的 Cloudflare Token 只在任务执行内存中保留，不写入任务数据库。系统默认的 Cloudflare Token 存在上述 root 专用配置文件。任务执行器重启时，中断的任务需重新提交 SSH 凭据。

## 多节点、共享域名与节点删除

- “SSH 读取已有节点”可以导入服务器已存在的 VLESS WS TLS 入站。
- 节点按服务器分组显示；点击“新增同服务器节点”，填写新 WS 路径与出口国家。可复用同一域名、公网映射端口，或添加新 TCP 端口。每个节点有自己的 UUID、链接和内部入站端口。
- 同一域名必须使用同一公网回源端口。nginx 按精确 WS 路径分流，例如 `/a` 和 `/b` 各对应一个节点。不同路径分别绑定出口；每个节点独立维护健康检查、热备和 20 Mbps 自动优选状态。
- 同域名、同路径再次提交会复用原有入站，避免重复创建。不同节点不会自动共用其他节点已管理的出口；该地区没有足够可用候选时可能没有热备或部署失败。
- 删除时重新输入 SSH 凭据和完整节点域名确认。执行器核对服务器、入站端口、WS 路径、SNI 与 UUID，再删除对应入站和独立守护；不会卸载 fanout、删除其他入站、共用证书或停止现有隧道。
- 同域名仍有其他节点时保留 DNS / 回源规则；最后一个节点删除后清理匹配源站 IP 的 DNS 和项目管理的精确主机名规则。规则指向已变化时拒绝清理，节点标记为“清理待重试”，可再次提交。未知或共享的 Cloudflare 规则不会被移除。
- 旧版多个入站共用守护的配置若删除主入站，会停用旧守护并在任务结果返回说明；其余入站保留，可重新部署以启用独立守护。

独立状态目录为 `/var/lib/fanout-nodes/<内部端口>/`，服务名为 `fanout-node-<内部端口>`。公网入口映射位于 `/var/lib/fanout-ingress/`，规则只重定向入站流量，保留原 Xray 监听。多个测速扫描通过共享锁排队，避免同时创建测速网络命名空间。

## 检查

```sh
python3 -m unittest discover -s tests -q
node --test web/control/scripts/test.mjs
# 可选：早期 Worker 适配器在构建产物存在后可运行 scripts/test-bridge.mjs
systemctl status vpn-control vpn-runner
```

备份 `/etc/vpn-control.json`、`/etc/vpn-runner.json`、`/var/lib/vpn-control/`、`/var/lib/vpn-runner/` 到私有位置。请勿提交真实配置、SSH 凭据、Cookie、节点订阅链接或状态数据库到 GitHub。
