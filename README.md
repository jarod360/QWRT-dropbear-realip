# QWRT Dropbear Proxy Protocol v2

This repository builds the Dropbear 2026.91 package for ImmortalWrt v24.10.6
(qualcommax/ipq807x / aarch64_cortex-a53) with trusted HAProxy Proxy Protocol v2
(PPv2) support. It builds package artifacts only; it does not build a firmware image.

## Behavior and trust boundary

- Only a TCP peer whose address is exactly 192.168.0.254 is treated as a trusted proxy.
- Connections from that peer must start with a valid PPv2 PROXY header for IPv4
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

Security note: trusting 192.168.0.254/32 means any process able to originate TCP
connections from that local address can claim a source address in PPv2.
Keep the proxy listener reachable only from the intended Lucky instance. Do not
expand this trust to the whole LAN unless that is an explicit security decision.

## Build

1. Open the GitHub Actions tab for this repository.
2. Run the "Build Dropbear PPv2 IPK" workflow, or push a change to main.
3. Download the artifact named dropbear-ppv2-immortalwrt-24.10.6-aarch64-cortex-a53.
4. Inspect the package metadata and target device compatibility before installing.

The workflow pins ImmortalWrt v24.10.6, the upstream Dropbear 2026.91 release
tarball and its SHA-256 hash, and PKG_RELEASE=3 (OpenWrt package version 2026.91-r3). It checks the
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
