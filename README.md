# QWRT Dropbear Proxy Protocol v2

This repository builds the Dropbear 2026.91 package for ImmortalWrt v24.10.6
(qualcommax/ipq807x / aarch64_cortex-a53) with trusted HAProxy Proxy Protocol v2
(PPv2) support. It builds package artifacts only; it does not build a firmware image.

## Behavior and trust boundary

- Trusted proxy peers are read from the UCI `ProxyProtocolTrusted` list. IPv4, IPv6, and CIDR entries are supported; no proxy address is compiled into the daemon.
- Connections from any configured trusted peer must start with a valid PPv2 PROXY header for IPv4
  or IPv6 TCP. Missing, malformed, unsupported, oversized, truncated, or
  timed-out headers are rejected. The connection is never downgraded to ordinary SSH.
- The header signature, version/command, family/protocol, total header size,
  address payload, and TLV boundaries are checked. The header is consumed
  before the SSH handshake. The parser has a 1 KiB cap and a five-second
  overall read deadline.
- The real source address is used before the unauthenticated per-IP connection
  limit is calculated, and for Dropbear connection logs, session address data,
  login/lastlog host values, SSH_CONNECTION, and SSH_CLIENT.
- Other peers do not have their initial bytes parsed as PPv2. Ordinary direct
  IPv4/IPv6 SSH connections keep their normal behavior.
- Dropbear's re-exec optimization is disabled in the package's local compile
  options so the already-parsed per-connection metadata remains available to
  the forked session. The normal fork-based listener remains enabled.

Security note: every address or CIDR in `ProxyProtocolTrusted` is allowed to
assert source addresses in PPv2. Keep this list as narrow as possible and
expose the listener only to the intended proxy.


## UCI configuration

The package defaults preserve the existing proxy address as an editable UCI
entry. Change the list to the actual address(es) of your trusted proxy:

```sh
uci set dropbear.main.ProxyProtocol='1'
uci -q delete dropbear.main.ProxyProtocolTrusted
uci add_list dropbear.main.ProxyProtocolTrusted='192.168.0.254/32'
uci add_list dropbear.main.ProxyProtocolTrusted='2001:db8:1234::/48'
uci commit dropbear
/etc/init.d/dropbear restart
```

Set `option ProxyProtocol '0'` to disable PPv2 trust. Multiple IPv4/IPv6
addresses and CIDR networks are supported. A peer matching the trusted list
must send a valid PPv2 header; invalid or missing headers are rejected.
Non-trusted peers continue to use ordinary SSH. An empty trusted list or a
missing runtime allow-list file means no peer is trusted.

## Build

1. Open the GitHub Actions tab for this repository.
2. Run the "Build Dropbear PPv2 IPK" workflow manually from the `realip-dev` branch. Commits to this branch do not trigger a build automatically.
3. Download the artifact named dropbear-ppv2-immortalwrt-24.10.6-aarch64-cortex-a53.
4. Inspect the package metadata and target device compatibility before installing.

The workflow pins ImmortalWrt v24.10.6, the upstream Dropbear 2026.91 release
tarball and its SHA-256 hash, and PKG_RELEASE=4 (OpenWrt package version 2026.91-r4). It checks the
package architecture and ELF metadata before uploading the result.

## Before installing on QWRT

This is an IPK built for ImmortalWrt 24.10.6, not a universal AArch64 binary.
The same aarch64_cortex-a53 architecture name by itself does not guarantee
target ABI, linked-library, package-manager, or configuration compatibility.
Check the device's release, package manager, opkg print-architecture (if
available), and the package's Depends field first. In particular, an APK-based
firmware may not accept an opkg-format IPK directly.

Before replacing the system SSH daemon, make sure you have a working fallback
access method and a copy of /etc/dropbear host keys and configuration. A
package install can restart Dropbear and interrupt active SSH sessions. Do not
test remotely without a recovery path.
