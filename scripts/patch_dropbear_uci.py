#!/usr/bin/env python3
"""Install UCI-driven trusted proxy configuration into ImmortalWrt Dropbear."""

from pathlib import Path
import sys

INIT_MARKER = "# QWRT Proxy Protocol v2 UCI support"
CONFIG_MARKER = "# QWRT Proxy Protocol v2: editable trusted proxy list"


def replace_once(path: Path, old: str, new: str, marker: str) -> None:
    data = path.read_text()
    if marker in data:
        print(f"Already patched: {path}")
        return
    if data.count(old) != 1:
        raise SystemExit(f"Patch anchor mismatch in {path}: expected one occurrence")
    path.write_text(data.replace(old, new, 1))
    print(f"Patched: {path}")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(f"Usage: {sys.argv[0]} OPENWRT_SOURCE_DIR")
    root = Path(sys.argv[1]).resolve()
    init = root / "package/network/services/dropbear/files/dropbear.init"
    config = root / "package/network/services/dropbear/files/dropbear.config"
    if not init.is_file() or not config.is_file():
        raise SystemExit("ImmortalWrt Dropbear init/config files were not found")

    replace_once(
        init,
        "\t\t'mdns:bool:1'\n",
        "\t\t'mdns:bool:1' \\\n"
        "\t\t'ProxyProtocol:bool:1' \\\n"
        "\t\t'ProxyProtocolTrusted:list(string)'\n",
        INIT_MARKER,
    )

    uci_functions = INIT_MARKER + """
# Build one root-owned runtime allow-list for all Dropbear instances.
# The daemon fails closed when this file is missing or contains no entries.
qwrt_pp2_add_trusted()
{
\t[ -n "$1" ] && printf '%s\\n' "$1" >> /var/run/dropbear-ppv2-trusted
}

qwrt_pp2_collect_section()
{
\tlocal enabled
\tconfig_get_bool enabled "$1" ProxyProtocol 1
\t[ "$enabled" = "1" ] || return 0
\tconfig_list_foreach "$1" ProxyProtocolTrusted qwrt_pp2_add_trusted
}

qwrt_pp2_prepare_trusted_file()
{
\tumask 077
\t: > /var/run/dropbear-ppv2-trusted
\tconfig_foreach qwrt_pp2_collect_section dropbear
\tchmod 0600 /var/run/dropbear-ppv2-trusted
}

"""
    replace_once(
        init,
        "start_service()\n{\n",
        uci_functions + "start_service()\n{\n",
        INIT_MARKER,
    )
    replace_once(
        init,
        '\tconfig_load "\${NAME}"\n\tconfig_foreach validate_section_dropbear dropbear dropbear_instance',
        '\tconfig_load "\${NAME}"\n\tqwrt_pp2_prepare_trusted_file\n'
        '\tconfig_foreach validate_section_dropbear dropbear dropbear_instance',
        "\tqwrt_pp2_prepare_trusted_file\n\tconfig_foreach validate_section_dropbear",
    )

    replace_once(
        config,
        "\toption Interface 'lan'\n",
        "\toption Interface 'lan'\n"
        "\t" + CONFIG_MARKER + "\n"
        "\toption ProxyProtocol '1'\n"
        "\tlist ProxyProtocolTrusted '192.168.0.254/32'\n",
        CONFIG_MARKER,
    )

    init_text = init.read_text()
    config_text = config.read_text()
    for marker in (
        "ProxyProtocol:bool:1",
        "ProxyProtocolTrusted:list(string)",
        "qwrt_pp2_prepare_trusted_file",
        "config_list_foreach",
    ):
        if marker not in init_text:
            raise SystemExit(f"UCI init verification failed: {marker}")
    for marker in ("option ProxyProtocol '1'", "list ProxyProtocolTrusted '192.168.0.254/32'"):
        if marker not in config_text:
            raise SystemExit(f"UCI defaults verification failed: {marker}")
    print("UCI Proxy Protocol v2 configuration verified")


if __name__ == "__main__":
    main()
