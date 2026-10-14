# QWRT Dropbear Proxy Protocol v2（真实客户端 IP）

本项目基于 ImmortalWrt v24.10.6 的 Dropbear 软件包，集成 HAProxy **Proxy Protocol v2（PPv2）** 支持，并通过 UCI 配置可信代理地址。

项目只编译并发布 Dropbear 软件包（IPK），**不编译完整固件**。

## 1. 本次构建信息

| 项目 | 构建结果 |
|---|---|
| OpenWrt 分支/版本 | ImmortalWrt v24.10.6 |
| Target | qualcommax |
| Subtarget | ipq807x |
| 软件包架构 | aarch64_cortex-a53 |
| Dropbear 上游版本 | 2026.91 |
| 软件包版本 | 2026.91-r4 |
| 软件包名称 | `dropbear_2026.91-r4_aarch64_cortex-a53.ipk` |
| 依赖 | libc |
| ELF | ELF64 / AArch64，动态链接 musl |

GitHub Actions 已对最终 IPK 执行软件包元数据、架构、版本、ELF 类型及 PPv2 特征检查。最近一次成功构建：

- [GitHub Actions #25](https://github.com/jarod360/QWRT-dropbear-realip/actions/runs/38505394719)
- [下载构建产物](https://github.com/jarod360/QWRT-dropbear-realip/actions/runs/38505394719#artifacts)

本次构建 IPK 的 SHA256：

```text
a3041ede3058e58f4f88efaa545eff13789ad505e84cc70aca597ab0984c32d4
```

> 注意：该软件包针对 ImmortalWrt v24.10.6 的 qualcommax/ipq807x 构建。不能仅凭设备是 AArch64 或 Cortex-A53 就认定兼容其他固件。

## 2. 功能与工作原理

### 2.1 可信代理判断

- 可信代理地址从 Dropbear 的 UCI 配置项 `ProxyProtocolTrusted` 读取。
- 支持 IPv4、IPv6 地址以及 CIDR 网段。
- 可信地址列表由 Dropbear 启动脚本生成到 `/var/run/dropbear-ppv2-trusted`。
- 守护进程不再将某个代理 IP 编译写死在 C 代码中。
- 运行时可信列表文件不存在或为空时，所有来源都不被视为可信代理。

### 2.2 PPv2 解析与连接处理

来自可信代理地址的连接必须首先发送有效的 Proxy Protocol v2 PROXY 头：

- 支持 IPv4/TCP 和 IPv6/TCP。
- 校验 PPv2 签名、版本、命令、地址族、传输协议、地址数据长度及 TLV 边界。
- 最大头部长度为 1024 字节。
- 固定头部和负载共用 5 秒读取期限，避免通过分段发送不断延长读取时间。
- 头部解析失败、缺失、超长、截断、格式不支持或超时，连接都会被拒绝。
- PPv2 头部在 SSH 握手前被读取并消费，不会传递给 SSH 识别过程。
- 不会在可信代理发送无效头部时降级为普通 SSH 连接。

本实现处理的是 PPv2 的 PROXY 命令及 IPv4/IPv6 TCP 地址信息；TLV 仅进行边界和长度校验，不解析其具体内容。不支持将 UDP 或 LOCAL 命令作为有效代理连接。

### 2.3 真实客户端 IP 的使用范围

解析得到的客户端地址用于：

- 未认证连接的单 IP 连接数限制。
- Dropbear 会话远端地址信息。
- 登录记录及 lastlog 使用的远端主机地址。
- SSH 会话环境中的远端地址信息（包括 SSH_CONNECTION、SSH_CLIENT 所使用的地址数据）。

非可信来源不会解析其连接开头的数据为 PPv2，普通直连 IPv4/IPv6 SSH 连接保持原有处理方式。

为保证解析后的每连接地址元数据能够在 fork 出来的会话进程中继续使用，构建时关闭 Dropbear 的 re-exec 优化（`DROPBEAR_REEXEC=0`）；正常的 fork 监听处理仍然保留。

## 3. UCI 配置

### 3.1 默认配置

构建补丁会在 Dropbear 默认配置中加入：

```sh
option ProxyProtocol '1'
list ProxyProtocolTrusted '192.168.0.254/32'
```

其中 `192.168.0.254/32` 是示例默认值，**不是固定要求**。请按实际部署修改为发送 PPv2 头部的代理服务器地址。不要填写客户端公网地址，除非客户端本身就是直接连接并发送 PPv2 的可信代理。

### 3.2 配置可信代理地址

例如 Lucky 的实际连接来源地址为 `192.168.0.254`：

```sh
uci set dropbear.main.ProxyProtocol='1'
uci -q delete dropbear.main.ProxyProtocolTrusted
uci add_list dropbear.main.ProxyProtocolTrusted='192.168.0.254/32'
uci commit dropbear
/etc/init.d/dropbear restart
```

如有多个可信代理，可重复添加：

```sh
uci add_list dropbear.main.ProxyProtocolTrusted='192.168.0.254/32'
uci add_list dropbear.main.ProxyProtocolTrusted='192.168.0.253/32'
uci add_list dropbear.main.ProxyProtocolTrusted='2001:db8:1234::/48'
uci commit dropbear
/etc/init.d/dropbear restart
```

查看当前配置：

```sh
uci show dropbear | grep -E 'ProxyProtocol'
cat /var/run/dropbear-ppv2-trusted
```

关闭 PPv2 可信代理处理：

```sh
uci set dropbear.main.ProxyProtocol='0'
uci commit dropbear
/etc/init.d/dropbear restart
```

启用 PPv2 后，可信列表中的来源必须发送有效的 PPv2 PROXY 头；如果该来源仍以普通 SSH 协议连接，连接会被拒绝。非可信来源仍按普通 SSH 连接处理。

如果设备有多个 Dropbear 配置段，启动脚本会遍历各个 `dropbear` 配置段：仅收集对应 `ProxyProtocol` 开关启用的配置段中的 `ProxyProtocolTrusted` 列表。

## 4. GitHub Actions 编译

工作流文件：

`.github/workflows/build-dropbear.yml`

编译流程主要包括：

1. 检出 ImmortalWrt v24.10.6 源码及本项目脚本。
2. 检查 PPv2 和 UCI 补丁脚本的 Python 语法。
3. 固定 Dropbear 上游版本为 2026.91，并校验源码 SHA256。
4. 注入 PPv2 Build/Prepare 补丁钩子及 UCI 可信代理配置。
5. 配置 `qualcommax/ipq807x`，并检查软件包架构为 `aarch64_cortex-a53`。
6. 预检查 Dropbear 剩余补丁是否能应用。
7. 准备、打补丁、配置并编译 Dropbear。
8. 再次运行 PPv2 补丁脚本，检查补丁幂等性。
9. 检查关键源码集成点、`DROPBEAR_REEXEC=0` 编译选项。
10. 检查最终 IPK 的版本、架构、依赖及 ELF 文件，并检查最终二进制中包含 PPv2 解析失败标记和运行时可信列表路径。
11. 上传 IPK、二进制和诊断日志作为 Actions Artifact。

工作流在 `main` 分支相关文件发生推送时自动触发，也支持手动触发。当前开发分支 `realip-dev` 可通过 GitHub Actions 的 **Run workflow** 手动启动。

产物名称：

`dropbear-ppv2-immortalwrt-24.10.6-aarch64-cortex-a53`

Artifact 默认保留 30 天。下载后请先核对文件名、版本和 SHA256。

## 5. 安装前检查

该 IPK 是针对 ImmortalWrt v24.10.6 构建的，不是通用 AArch64 软件包。安装前请确认：

1. 设备的固件版本及软件包来源与构建目标兼容。
2. 设备的软件包管理器和 IPK 格式兼容。
3. 软件包架构与设备的软件包架构列表匹配。
4. 软件包依赖满足要求（本次构建的 Depends 为 `libc`）。
5. 设备使用的 musl ABI、动态加载器及相关运行库兼容。

尤其注意：使用 APK 的固件不一定能直接安装 opkg 格式的 IPK。架构名称相同也不代表 ABI、依赖和配置完全兼容。

## 6. 安全注意事项

- `ProxyProtocolTrusted` 中的每个地址或网段都被授权声明 PPv2 中的客户端源地址。
- 可信代理列表必须尽可能精确，不要随意添加整个公网网段。
- SSH 监听端口应通过防火墙限制为仅允许预期代理访问，避免其他来源直接访问。
- PPv2 只负责传递代理声明的源地址，不负责验证该源地址是否真实；可信代理本身必须可靠。
- 替换系统 SSH 服务前，先准备本地控制台或其他可用的恢复通道，并备份 `/etc/dropbear` 下的主机密钥及配置。
- 安装软件包可能重启 Dropbear 并中断当前 SSH 会话。不要在没有恢复手段的情况下远程直接替换 SSH 服务。

## 7. 项目文件

- `scripts/patch_dropbear_ppv2.py`：向 Dropbear 2026.91 源码集成 PPv2 解析、可信代理判断和真实地址传递。
- `scripts/patch_dropbear_uci.py`：修改 Dropbear init/config 文件，增加 UCI 选项并生成运行时可信代理列表。
- `.github/workflows/build-dropbear.yml`：自动化编译、检查和上传构建产物。
- `README.md`：项目说明、配置及安装注意事项。
