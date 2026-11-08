# 上游与依赖

- [byJoey/fanout](https://github.com/byJoey/fanout)：MIT，Copyright (c) 2026 Joey (byJoey)。本项目通过其管理 API 操作出口和 native Xray 入站；命名空间、OpenVPN 参数和家宽筛选策略参考该项目。保留其 MIT 许可全文于 `licenses/fanout-MIT.txt`。
- [XTLS/Xray-core](https://github.com/XTLS/Xray-core)：运行时依赖，由现有 fanout 安装提供，本仓库不分发其二进制。
- [OpenVPN](https://github.com/OpenVPN/openvpn)：运行时依赖，由操作系统包管理器安装。
- [VPN Gate](https://www.vpngate.net/)：公共志愿者 VPN 节点和列表来源。公共出口可用性、带宽及地址均会变化。
- [Cloudflare](https://www.cloudflare.com/)：前端代理和测速服务；本项目使用其公开下载测速端点。

上游接口、客户端版本和公共测速服务可能变化。部署时应遵守各项服务的使用规则。
