# vpn-socks

给 [byJoey/fanout](https://github.com/byJoey/fanout) 增加同地区出口热备、Cloudflare → VLESS 完整链路检测，以及低带宽触发的出口库自动优选。支持日本 `JP` 和韩国 `KR`，每台服务器只从选定国家的出口库选择主备。适用于已经配置好 VLESS WebSocket、Cloudflare 端口回源的 Alpine/OpenRC NAT 服务器。

## 默认策略

| 项目 | 默认值 |
|---|---|
| 低速阈值 | **20 Mbps**，约 2.5 MB/s，按完整 CF 链路计算 |
| 带宽抽测 | 每 5 分钟，最多下载 8 MB，最多等待 12 秒 |
| 触发条件 | 同一当前出口连续 3 次有效测速低于阈值 |
| 全库扫描冷却 | 扫描开始后至少间隔 1 小时 |
| 候选范围 | 最新 VPN Gate 列表中选定国家、通过上游家宽筛选的节点 |
| 扫描 | 独立网络命名空间逐个连接、核验出口 IP、下载测速 |
| 复测 | 首轮结果从快到慢，最多收集 6 个通过双次复测的候选 |
| 替换 | 按复测结果选择最快、第二快的不同出口作为主备 |
| 生效检查 | 主出口通过 CF 链路验证、备用再次连通，才清理旧的受管出口 |
| 最小收益 | 新 CF 路径相对触发时样本至少提升 20%，否则请求恢复原出口 |
| 断网恢复 | 独立健康守护继续工作；扫描期间保持旧出口和客户端参数 |

节点 UUID、WS 路径、客户端域名及 CF 回源规则不随出口替换而改变。切换会重启 fanout 管理的 Xray，现有连接可能中断。公共出口速度会变化，测速排名代表当次测量。

“家宽”沿用上游的启发式筛选：排除 `public-vpn-*` 和 `219.100.37.0/24`，并非运营商或住宅属性的独立认证。只有可连接、能正常下载、且出口 IP 符合预期的候选会参与排名。

## 安装前准备

- Alpine Linux / OpenRC、root，以及可用的 `/dev/net/tun`、network namespace、veth、iptables 转发。
- 按 [fanout 上游说明](https://github.com/byJoey/fanout#安装)安装 fanout，使用 **native Xray** 后端。Xray 路径为 `/var/lib/fanout/bin/xray`；管理端口从 `/var/lib/fanout/settings.json` 自动读取，建议仅本机监听。
- 在 fanout 中创建 `33002` 的 VLESS WS 入站，以及 `33003` 的 VLESS WS TLS 入站。两者使用同一个日本出口；另创建一条没有绑定入站的日本备用出口。
- 设置 CF 橙云域名、目的端口 **33003**，确保现有节点已经能经 CF 访问。源站若为自签证书，主机名使用 CF Full 模式；可信源站证书可以使用 Full (strict)。
- 默认使用上述节点端口；可通过安装参数指定单个 TLS 入站端口。入站 tag 和地区写入 `/etc/fanout-ha.json`。本机健康代理固定为 `127.0.0.1:10809` / `10810`。

```sh
git clone https://github.com/zhangx16/vpn-socks.git
cd vpn-socks
sh install.sh node.example.com
```

将 `node.example.com` 替换为已配置的 CF 节点域名。安装器从服务器现有的 fanout 私有配置读取 UUID、路径和证书，生成只监听本机的健康客户端，不要求将凭据写入项目。

只有一个可用公网端口的韩国部署示例：先在 fanout 创建 **35001** 的 VLESS WS TLS 入站，绑定韩国出口，再创建一条未绑定的韩国热备。CF 回源端口设为 35001，然后运行：

```sh
sh install.sh kr.example.com KR 35001
```

管理界面仍可使用任意空闲本机端口，例如 `127.0.0.1:33011`；通过 SSH 转发访问，无需占用公开端口。该模式只操作 `in-35001-ws`，全库扫描、故障恢复和热备均限定在韩国。

安装器首次采用选定国家的当前出口及一条未绑定的同国家备用出口作为受管主备。此后只清理该受管集合和优化器自己创建的临时出口，不删除其他已有入站绑定。受管槽位保存在 `/var/lib/fanout-speed/managed-slots.json`。

若 LXC 中 `ip netns exec` 报 `/sys` 挂载权限错误，而 `nsenter --net=...` 可用，可以启用已提供的兼容包装：

```sh
FANOUT_LXC_COMPAT=1 sh install.sh node.example.com
```

它只修改 fanout 服务的 PATH；启用时会重启 fanout，短暂中断现有连接。

在此兼容模式中，`nsenter` 会保留宿主的 DNS 配置。若 DNS 是 RFC1918 内网 IPv4 地址，包装器和扫描器会在各自命名空间内为该 DNS 添加经宿主网关的专用路由，避免 OpenVPN 默认路由把内网 DNS 请求送入 VPN。宿主 DNS 配置保持原样；这些 DNS 查询由宿主 DNS 处理，业务连接经过所选 VPN 出口。

## 工作流程

```mermaid
flowchart TD
    A[每 5 分钟测完整 CF 链路] --> B{连续 3 次低于 20 Mbps?}
    B -- 否 --> A
    B -- 是 --> C{距上轮扫描已超过 1 小时?}
    C -- 否 --> A
    C -- 是 --> D[刷新出口库并逐个实测]
    D --> E[速度靠前候选双次复测]
    E --> F[建立最快和第二快的不同出口]
    F --> G[请求健康守护切换并验证 CF 链路]
    G --> H{验证和收益检查通过?}
    H -- 是 --> I[保留新主备并清理旧受管出口]
    H -- 否 --> J[保留旧出口或请求恢复原出口]
    I --> A
    J --> A
```

带宽守护和健康守护是两个进程。全库扫描可能持续数分钟，期间断网自动切换仍由健康守护负责。测速目标 HTTP 错误或不可达不计为低速；HTTP 200 下载因超时仅取得部分数据时，按已下载字节计算速度。更换当前出口会重置连续低速计数。

没有两条候选通过复测、连接失败、出口不符、CF 验证失败或收益不足时，不会清空原有主备。恢复原出口也依赖原出口当时可用；若它同时故障，由健康守护继续恢复。

## 修改阈值

配置文件：`/etc/fanout-speed.json`。每轮检查重新读取配置，无需重启：

```json
{
  "threshold_mbps": 20,
  "check_interval_seconds": 300,
  "consecutive_low": 3,
  "scan_cooldown_seconds": 3600,
  "sample_bytes": 8000000,
  "sample_timeout_seconds": 12,
  "finalists": 6,
  "minimum_gain_ratio": 1.2
}
```

Mbps 为十进制兆比特每秒，MB/s 为十进制兆字节每秒。抽测按默认值每天最多约 2.3 GB 下载流量；一次 35 节点扫描的理论下载上限约 236 MB（35×4 MB 首测，加 6×2×8 MB 复测），另有少量连通性和应用验证流量。扫描失败也受冷却限制。实际候选数量随公共出口库变化。

## 状态和维护

```sh
rc-service fanout-ha status
rc-service fanout-probe status
rc-service fanout-speed status
cat /var/lib/fanout-ha/status.json
cat /var/lib/fanout-speed/state.json
cat /var/lib/fanout-speed/selection.json
tail -n 50 /var/log/fanout-speed.log
```

`state.json` 包含最近 CF 测速、阈值、连续低速次数、扫描状态和最近错误。全库进度位于它的 `scan_directory` 对应的 `progress.log`。最多保留最近三轮扫描报告。

手动执行一轮采样或立即扫描时，先停带宽守护以释放锁。健康守护保持运行：

```sh
rc-service fanout-speed stop
fanout-speed --once       # 一次采样，达到条件时会扫描
# 或 fanout-speed --scan-now  # 跳过连续次数和冷却，立即验证一轮扫描
rc-service fanout-speed start
```

仅暂停带宽优化：`rc-service fanout-speed stop`。取消开机启动：`rc-update del fanout-speed default`。健康守护可继续工作。修改现有 VLESS UUID、域名或 WS 路径后，重新运行安装器生成健康配置。

服务日志按天、最大 1 MB 触发轮转，保留四份。报告、密码、证书、运行时状态都保存在服务器私有目录，禁止提交到 Git。

## 测试

```sh
python3 -m unittest discover -s tests -v
python3 -m py_compile bin/fanout-speed libexec/scan-jp scripts/configure-probes.py
bash -n bin/fanout-ha
sh -n install.sh
```

单元测试覆盖 20 Mbps 边界、连续计数、出口变更、测速错误、冷却和出口清理保护。真实扫描、主备切换及 CF 验证需要配置好上述环境；测试不会主动连接真实 VPN Gate 节点。

## 文件

- `bin/fanout-ha`：完整链路健康守护与串行切换请求处理。
- `bin/fanout-speed`：低速检测、扫描编排、主备替换和回滚请求。
- `libexec/scan-jp`：独立命名空间中的出口库测速。
- `scripts/configure-probes.py`：读取本机私有配置，生成 CF 和源站健康客户端。
- `openrc/`：三个进程的守护和开机自启服务。

依赖与许可见 [THIRD_PARTY.md](THIRD_PARTY.md)。

## 网页任务台

`web/control/` 提供仅本人可访问的 Sites 控制页：选择节点后，一键设置 Cloudflare 橙云 A 记录、Origin Rules 回源端口、主机名级 TLS Full/Strict，并通过 WebSocket 握手验收。支持只读检查、失败时恢复本次已完成的写入、逐步进度、导出结果和不含凭据的本机任务摘要。

CF Token 存在 Sites 的服务器运行时 Secret `CF_API_TOKEN` 中；节点预设使用 Secret `NODE_PRESETS`。源代码不包含实际 Token、服务器密码或节点私有配置。所需权限为 `Zone → Zone → Read`、`Zone → DNS → Edit`、`Zone → Origin Rules → Edit`、`Zone → Config Rules → Edit`，资源限定为目标 Zone。

该页面负责 CF 配置和链路验收；服务器上的出口健康检测与 20 Mbps 自动优选仍由上述 OpenRC 服务运行。WebSocket 握手成功不能独立证明最终 VPN 出口位置，完整代理出口仍应通过节点客户端检查。

构建前将 `web/control/.openai/hosting.example.json` 复制为 `.openai/hosting.json` 并填入当前 Sites 的项目 ID。保持 Site 为 owner-private，API 依赖 Sites 注入的已登录身份，不应直接部署为未经认证的公开 Worker。

```sh
cd web/control
node --test scripts/test.mjs
bash scripts/build.sh
node scripts/validate-artifact.mjs
```
