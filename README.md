# QWRT Dropbear RealIP（Proxy Protocol v2）

基于 ImmortalWrt v24.10.6 / Dropbear 2026.91，为 SSH 增加 **Proxy Protocol v2 (PPv2)** 解析。仅在明确启用并设置信任代理后生效，**新安装默认关闭**。项目通过 GitHub Actions 生成适用于指定目标的 IPK，不构建完整固件。

> 注意：PPv2 与 HTTP 的 `X-Real-IP` 不是同一协议。SSH 使用本项目；LuCI/uhttpd 使用 [QWRT-uhttpd-realip](https://github.com/jarod360/QWRT-uhttpd-realip)。现有历史构建产物可能仍为旧的“默认开启”版本；请使用包含此修改的新构建，勿把新文档视为旧 IPK 的运行行为。

## 默认行为及安全原则

- `option ProxyProtocol '0'`：**默认关闭**。此时不向运行时可信代理列表写入任何地址，Dropbear 按普通 SSH 连接处理；即使客户端发送 PPv2 头，也不会作为 PPv2 解析。
- `list ProxyProtocolTrusted`：可信代理 IP 或 CIDR，默认**没有任何有效条目**。例子仅作为注释，不会信任 `192.168.0.254`。
- 启用后，只有源 TCP 地址符合可信代理列表的连接才尝试解析 PPv2；来自这些代理的连接必须携带有效的 PPv2 头，否则拒绝。其他来源仍使用普通 SSH。
- 即使开关设置为 1，可信列表不存在或为空时也不信任任何代理。运行时文件：`/var/run/dropbear-ppv2-trusted`。
- 当前实现支持 IPv4/IPv6 与 CIDR、PPv2 的 IPv4/IPv6 TCP 地址、最长 1024 字节的头以及最长 5 秒的读取期限。
- 为保留子进程的真实客户端地址元数据，构建使用 `DROPBEAR_REEXEC=0`。即使 PPv2 关闭，这也是与原始构建不同的内部运行方式；不能仅凭开关关闭就声称二进制与上游完全相同。

## UCI 命令行使用

以下示例基于默认 `dropbear.main` 配置段；如果固件实际使用匿名段（例如 `dropbear.@dropbear[0]`），需将所有命令中的 `dropbear.main` 改为对应段。先查看实际段名：

```sh
uci show dropbear
```

**查看状态**（确认开关、可信列表、运行时实际启用的代理）：

```sh
uci -q get dropbear.main.ProxyProtocol || echo 0
uci -q show dropbear.main.ProxyProtocolTrusted
cat /var/run/dropbear-ppv2-trusted 2>/dev/null
```

**启用并指定可信代理**。示例代理地址为 `192.168.0.254`，必须按你的代理真实 TCP 来源 IP 修改；并且代理必须发送 **PPv2**，不能是普通 SSH 转发。

```sh
uci -q delete dropbear.main.ProxyProtocolTrusted
uci add_list dropbear.main.ProxyProtocolTrusted='192.168.0.254/32'
uci set dropbear.main.ProxyProtocol='1'
uci commit dropbear
/etc/init.d/dropbear restart
```

**添加第二个可信代理**（按需使用）：

```sh
uci add_list dropbear.main.ProxyProtocolTrusted='192.168.0.253/32'
uci commit dropbear
/etc/init.d/dropbear restart
```

**关闭 PPv2，恢复普通 SSH 连接处理**（保留可信地址列表便于日后再次启用）：

```sh
uci set dropbear.main.ProxyProtocol='0'
uci commit dropbear
/etc/init.d/dropbear restart
```

**清空可信列表**：

```sh
uci -q delete dropbear.main.ProxyProtocolTrusted
uci commit dropbear
/etc/init.d/dropbear restart
```

对于升级安装，已有 `/etc/config/dropbear` 可能被软件包管理器保留；因此**默认关闭仅保证新生成的配置和未设置开关的情况**。如果旧配置中 `ProxyProtocol='1'`，请使用上面的关闭命令显式关掉。

如果有多个 Dropbear 段，运行时列表会汇总所有明确启用 PPv2 的段的可信地址，**不是按监听端口单独隔离**。若只希望某一端口支持 PPv2，应使用独立的守护进程或限制其他端口的网络访问，不要把共享开关误解为逐监听口的隔离。

## 编译和兼容性

`.github/workflows/build-dropbear.yml` 使用 ImmortalWrt `v24.10.6`、目标 `qualcommax/ipq807x`，目标软件包架构 `aarch64_cortex-a53`，Dropbear `2026.91-r4`。

在仓库 GitHub Actions 页面选择 **Build Dropbear PPv2 IPK → Run workflow**，构建完成后下载 artifact：`dropbear-ppv2-immortalwrt-24.10.6-aarch64-cortex-a53`。

构建输出以本次运行记录为准。历史成功运行及其 SHA256 仅对应旧产物，不能证明当前修改已编译成功。安装前应核对设备固件、依赖、架构、软件包格式和 ABI；仅有 `aarch64_cortex-a53` 并不足以证明兼容。

## 防止 SSH 失联

部署前**备份 `/etc/config/dropbear` 和 `/etc/dropbear` 主机密钥**，并准备串口/本机终端或第二条管理通道。覆盖 SSH 服务器可能中断当前会话。切换 PPv2 时，在另一条连接确认新 SSH 登录成功后再关闭旧连接。

从普通 SSH 客户端访问列在 `ProxyProtocolTrusted` 的来源 IP 时，如果开关开启、代理没有发送 PPv2，连接会被拒绝；**关掉开关即可恢复普通 SSH 处理**。

## 源码说明

- `scripts/patch_dropbear_ppv2.py`：Dropbear PPv2 解析、真实客户端地址传递和可信来源判断。
- `scripts/patch_dropbear_uci.py`：UCI 配置、缺省关闭、生成运行时可信代理列表。
- `.github/workflows/build-dropbear.yml`：IPK 构建、源码和产物检查。
