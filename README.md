# QWRT Dropbear Proxy Protocol v2（真实客户端 IP）

本项目为 ImmortalWrt 的 Dropbear 集成 HAProxy **Proxy Protocol v2（PPv2）** 支持，使 Dropbear 能在可信代理转发 SSH 连接时识别真实客户端 IP。

项目只编译并发布 Dropbear 软件包（IPK），**不编译完整固件**。当前包含 UCI 可配置可信代理列表的实现位于 `realip-dev` 分支。

## 1. 当前已验证的构建版本

| 项目 | 结果 |
|---|---|
| 固件源码 | ImmortalWrt v24.10.6 |
| Target / Subtarget | qualcommax / ipq807x |
| 软件包架构 | aarch64_cortex-a53 |
| Dropbear 上游版本 | 2026.91 |
| 软件包版本 | 2026.91-r4 |
| 软件包 | `dropbear_2026.91-r4_aarch64_cortex-a53.ipk` |
| 依赖 | libc |
| ELF | ELF64 / AArch64，动态链接 musl |

最近一次成功构建：[#25 - GitHub Actions](https://github.com/jarod360/QWRT-dropbear-realip/actions/runs/38505394719)。

[下载该次构建产物](https://github.com/jarod360/QWRT-dropbear-realip/actions/runs/38505394719#artifacts)

本次 IPK 的 SHA256：

```text
a3041ede3058e58f4f88efaa545eff13789ad505e84cc70aca597ab0984c32d4
```

> 重要：这是针对 ImmortalWrt v24.10.6 的 qualcommax/ipq807x 目标构建的软件包。不能仅凭设备是 AArch64 或 Cortex-A53 就认定兼容其他固件。

## 2. 功能说明

- 可信代理从 UCI 的 `ProxyProtocolTrusted` 列表读取，支持 IPv4、IPv6 和 CIDR 网段；代理地址不再编译写死在守护进程中。
- Dropbear 启动脚本将启用的可信代理列表写入 `/var/run/dropbear-ppv2-trusted`。运行时文件缺失或为空时，不信任任何代理。
- 可信代理连接必须携带有效的 PPv2 PROXY 头；缺失、格式错误、超长、截断、超时或不支持的头部都会被拒绝，不会降级为普通 SSH。
- 支持 IPv4/TCP、IPv6/TCP；检查 PPv2 签名、版本/命令、地址族/传输协议、地址长度和 TLV 边界。TLV 只检查边界，不解析具体内容。
- PPv2 头部最大 1024 字节，固定头部和负载共用 5 秒读取期限，并在 SSH 握手前消费。
- 解析出的真实客户端地址用于未认证连接数限制、会话远端地址及登录记录等地址数据。
- 非可信来源不解析 PPv2，普通直连 SSH 保持原有处理方式。
- 构建时设置 `DROPBEAR_REEXEC=0`，保留 fork 会话中所需的每连接地址元数据；正常 fork 监听机制仍然启用。

## 3. UCI 配置（realip-dev 分支）

默认配置中提供以下示例：

```sh
option ProxyProtocol '1'
list ProxyProtocolTrusted '192.168.0.254/32'
```

`192.168.0.254/32` 只是默认示例，请替换为实际发送 PPv2 头部的代理服务器来源地址。

配置单个可信代理：

```sh
uci set dropbear.main.ProxyProtocol='1'
uci -q delete dropbear.main.ProxyProtocolTrusted
uci add_list dropbear.main.ProxyProtocolTrusted='192.168.0.254/32'
uci commit dropbear
/etc/init.d/dropbear restart
```

添加多个可信代理：

```sh
uci add_list dropbear.main.ProxyProtocolTrusted='192.168.0.253/32'
uci add_list dropbear.main.ProxyProtocolTrusted='2001:db8:1234::/48'
uci commit dropbear
/etc/init.d/dropbear restart
```

查看配置和运行时可信列表：

```sh
uci show dropbear | grep -E 'ProxyProtocol'
cat /var/run/dropbear-ppv2-trusted
```

关闭 PPv2：

```sh
uci set dropbear.main.ProxyProtocol='0'
uci commit dropbear
/etc/init.d/dropbear restart
```

可信代理列表中的来源必须发送有效 PPv2 头部；普通 SSH 连接若来自可信代理地址会被拒绝。非可信来源仍按普通 SSH 处理。

## 4. 编译流程

工作流位于 `.github/workflows/build-dropbear.yml`。当前开发分支 `realip-dev` 使用手动触发；`main` 分支相关文件推送也可触发工作流。

主要步骤：

1. 检出 ImmortalWrt v24.10.6 和项目代码。
2. 检查 PPv2、UCI 补丁脚本语法。
3. 固定 Dropbear 2026.91 上游源码并校验 SHA256。
4. 注入 PPv2 Build/Prepare 钩子、UCI 配置和运行时可信列表生成逻辑。
5. 配置并验证 qualcommax/ipq807x 与 aarch64_cortex-a53 架构。
6. 预检查剩余 Dropbear 补丁。
7. 准备、打补丁、配置和编译 Dropbear；重复执行 PPv2 补丁以验证幂等性。
8. 检查 PPv2 源码集成点及 `DROPBEAR_REEXEC=0`。
9. 检查最终 IPK 的版本、架构、依赖、ELF 类型和 PPv2 特征字符串。
10. 上传 IPK、二进制和诊断日志。

Artifact 名称：

`dropbear-ppv2-immortalwrt-24.10.6-aarch64-cortex-a53`

Artifact 保留 30 天。请以具体 Actions 运行记录和产物校验值为准。

## 5. 安装前兼容性检查

本次软件包针对 ImmortalWrt v24.10.6 构建，并非通用 AArch64 软件包。安装前请确认：

- 设备固件版本、目标平台和软件包 ABI 兼容。
- 软件包管理器支持 IPK 格式；APK 固件不一定能直接安装 opkg 格式 IPK。
- 软件包架构与设备架构匹配。
- 依赖满足要求。本次构建的 Depends 为 `libc`。
- 设备使用的 musl 动态加载器及相关运行库兼容。

**架构名称相同不代表 ABI、依赖和配置一定兼容。**

## 6. 安全注意事项

- 可信代理列表中的每个地址/网段都被授权声明 PPv2 中的客户端源地址，请尽量使用精确的代理 IP 或最小 CIDR。
- PPv2 传递的是代理声明的地址，不负责验证该地址是否真实；必须信任代理本身。
- 建议通过防火墙限制 SSH 监听端口，只允许预期代理访问。
- 替换系统 SSH 服务前，准备本地控制台或其他恢复通道，并备份 `/etc/dropbear` 主机密钥和配置。
- 安装可能重启 Dropbear 并中断当前 SSH 会话，不要在没有恢复手段时远程直接替换。

## 7. 项目文件

- `scripts/patch_dropbear_ppv2.py`：集成 PPv2 解析、可信代理判断及真实地址传递。
- `scripts/patch_dropbear_uci.py`：注入 UCI 选项，并在 Dropbear 启动时生成运行时可信代理列表。
- `.github/workflows/build-dropbear.yml`：自动化编译、检查和上传产物。
- `README.md`：项目说明、配置方法及安装注意事项。
