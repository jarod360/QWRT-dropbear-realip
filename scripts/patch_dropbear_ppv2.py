#!/usr/bin/env python3
"""Apply the QWRT Dropbear Proxy Protocol v2 patch to Dropbear 2026.91."""

from pathlib import Path
import sys

MARKER = "Rejecting connection from trusted proxy: invalid Proxy Protocol v2 header"


def replace_once(path: Path, old: str, new: str, marker: str) -> None:
    text = path.read_text()
    if marker in text:
        print(f"Already patched: {path}")
        return
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"Patch anchor mismatch in {path}: expected exactly 1 occurrence, found {count}"
        )
    path.write_text(text.replace(old, new, 1))
    print(f"Patched: {path}")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(f"Usage: {sys.argv[0]} DROPBEAR_SOURCE_DIR")
    root = Path(sys.argv[1]).resolve()
    if not (root / "src/svr-main.c").is_file():
        raise SystemExit(f"Not a Dropbear source directory: {root}")

    main_helpers = r'''
/*
 * QWRT Proxy Protocol v2 support.
 * Trusted peers are read from the UCI-generated runtime file. Each entry
 * accepts an IPv4/IPv6 address or CIDR; an empty/missing file trusts nobody.
 */
#include <stdio.h>
#include <stdlib.h>
#include <arpa/inet.h>
#define QWRT_PP2_MAX_HEADER 1024
#define QWRT_PP2_TIMEOUT_SECONDS 5
#define QWRT_PP2_TRUSTED_FILE "/var/run/dropbear-ppv2-trusted"

static struct sockaddr_storage qwrt_pp2_remoteaddr;
static int qwrt_pp2_remoteaddr_active;
static int qwrt_pp2_remoteaddr_sock = -1;

static int qwrt_pp2_match_prefix(const unsigned char *address,
                                 const unsigned char *network,
                                 unsigned int prefix, unsigned int maxbits)
{
    unsigned int bytes, bits;
    if (prefix > maxbits) return 0;
    bytes = prefix / 8;
    bits = prefix % 8;
    if (bytes && memcmp(address, network, bytes) != 0) return 0;
    if (bits) {
        unsigned char mask = (unsigned char)(0xffU << (8 - bits));
        if ((address[bytes] & mask) != (network[bytes] & mask)) return 0;
    }
    return 1;
}

static int qwrt_pp2_match_cidr(const struct sockaddr_storage *peer,
                               const char *entry)
{
    char address[INET6_ADDRSTRLEN + 6];
    char *slash, *end;
    unsigned long prefix;
    struct in_addr v4;
    struct in6_addr v6;

    if (!entry || !*entry || strlen(entry) >= sizeof(address) + 5) return 0;
    snprintf(address, sizeof(address), "%s", entry);
    slash = strchr(address, '/');
    if (slash) {
        *slash++ = '\0';
        if (!*slash) return 0;
        prefix = strtoul(slash, &end, 10);
        if (*end || prefix > 128) return 0;
    } else {
        prefix = (unsigned long)-1;
    }

    if (peer->ss_family == AF_INET) {
        const struct sockaddr_in *sin = (const struct sockaddr_in *)peer;
        if (inet_pton(AF_INET, address, &v4) != 1) return 0;
        if (prefix == (unsigned long)-1) prefix = 32;
        return qwrt_pp2_match_prefix((const unsigned char *)&sin->sin_addr,
                                     (const unsigned char *)&v4,
                                     (unsigned int)prefix, 32);
    }
    if (peer->ss_family == AF_INET6) {
        const struct sockaddr_in6 *sin6 = (const struct sockaddr_in6 *)peer;
        if (IN6_IS_ADDR_V4MAPPED(&sin6->sin6_addr)) {
            struct in_addr peer4;
            if (inet_pton(AF_INET, address, &v4) != 1) return 0;
            if (prefix == (unsigned long)-1) prefix = 32;
            if (prefix > 32) return 0;
            memcpy(&peer4, &sin6->sin6_addr.s6_addr[12], sizeof(peer4));
            return qwrt_pp2_match_prefix((const unsigned char *)&peer4,
                                         (const unsigned char *)&v4,
                                         (unsigned int)prefix, 32);
        }
        if (inet_pton(AF_INET6, address, &v6) != 1) return 0;
        if (prefix == (unsigned long)-1) prefix = 128;
        return qwrt_pp2_match_prefix((const unsigned char *)&sin6->sin6_addr,
                                     (const unsigned char *)&v6,
                                     (unsigned int)prefix, 128);
    }
    return 0;
}

static int qwrt_pp2_is_trusted_proxy(const struct sockaddr_storage *peer)
{
    FILE *fp;
    char line[INET6_ADDRSTRLEN + 8];
    int trusted = 0;

    fp = fopen(QWRT_PP2_TRUSTED_FILE, "r");
    if (!fp) return 0;
    while (fgets(line, sizeof(line), fp)) {
        line[strcspn(line, "\r\n")] = '\0';
        if (qwrt_pp2_match_cidr(peer, line)) {
            trusted = 1;
            break;
        }
    }
    fclose(fp);
    return trusted;
}

/* Read exactly len bytes before one shared five-second deadline, including
 * partial reads. The parser passes the same deadline for the fixed header and
 * payload so a slow peer cannot reset the timeout between them. */
static int qwrt_pp2_read_exact(int fd, unsigned char *buf, size_t len,
                               const struct timeval *deadline)
{
    size_t offset = 0;

    while (offset < len) {
        struct timeval now, timeout;
        fd_set readfds;
        int ready;
        ssize_t got;

        if (gettimeofday(&now, NULL) < 0) {
            return -1;
        }
        timeout.tv_sec = deadline->tv_sec - now.tv_sec;
        timeout.tv_usec = deadline->tv_usec - now.tv_usec;
        if (timeout.tv_usec < 0) {
            timeout.tv_sec--;
            timeout.tv_usec += 1000000;
        }
        if (timeout.tv_sec < 0 ||
            (timeout.tv_sec == 0 && timeout.tv_usec == 0)) {
            return -1;
        }

        FD_ZERO(&readfds);
        FD_SET(fd, &readfds);
        ready = select(fd + 1, &readfds, NULL, NULL, &timeout);
        if (ready < 0) {
            if (errno == EINTR) {
                continue;
            }
            return -1;
        }
        if (ready == 0) {
            return -1;
        }

        got = recv(fd, buf + offset, len - offset, 0);
        if (got < 0) {
            if (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK) {
                continue;
            }
            return -1;
        }
        if (got == 0) {
            return -1;
        }
        offset += (size_t)got;
    }

    return 0;
}

/* Parse a PROXY protocol v2 PROXY command carrying IPv4/IPv6 STREAM.
 * Address metadata is returned separately; the PROXY bytes are consumed
 * before fork(), so they are never passed to the SSH identification parser.
 * TLVs are not interpreted, but each TLV's full boundary is validated. */
static int qwrt_pp2_parse(int fd, struct sockaddr_storage *realaddr,
                          socklen_t *realaddrlen)
{
    static const unsigned char signature[12] = {
        0x0d, 0x0a, 0x0d, 0x0a, 0x00, 0x0d,
        0x0a, 0x51, 0x55, 0x49, 0x54, 0x0a
    };
    unsigned char header[QWRT_PP2_MAX_HEADER];
    unsigned int payload_len, address_len, offset;
    struct timeval deadline;

    if (gettimeofday(&deadline, NULL) < 0) {
        return -1;
    }
    deadline.tv_sec += QWRT_PP2_TIMEOUT_SECONDS;
    if (qwrt_pp2_read_exact(fd, header, 16, &deadline) < 0) {
        return -1;
    }
    if (memcmp(header, signature, sizeof(signature)) != 0) {
        return -1;
    }

    /* Version 2, command PROXY (0x21); only IPv4/IPv6 over TCP are accepted. */
    if (header[12] != 0x21 ||
        (header[13] != 0x11 && header[13] != 0x21)) {
        return -1;
    }

    payload_len = ((unsigned int)header[14] << 8) | header[15];
    if (payload_len > sizeof(header) - 16) {
        return -1;
    }
    if (qwrt_pp2_read_exact(fd, header + 16, payload_len, &deadline) < 0) {
        return -1;
    }

    address_len = (header[13] == 0x11) ? 12 : 36;
    if (payload_len < address_len) {
        return -1;
    }

    /* Validate all trailing TLVs, including the length of every value. */
    offset = address_len;
    while (offset < payload_len) {
        unsigned int tlv_len;
        if (payload_len - offset < 3) {
            return -1;
        }
        tlv_len = ((unsigned int)header[16 + offset + 1] << 8) |
                  header[16 + offset + 2];
        offset += 3;
        if (tlv_len > payload_len - offset) {
            return -1;
        }
        offset += tlv_len;
    }

    memset(realaddr, 0, sizeof(*realaddr));
    if (header[13] == 0x11) {
        struct sockaddr_in *sin = (struct sockaddr_in *)realaddr;
        sin->sin_family = AF_INET;
        memcpy(&sin->sin_addr, header + 16, 4);
        memcpy(&sin->sin_port, header + 16 + 8, 2);
        *realaddrlen = sizeof(*sin);
    } else {
        struct sockaddr_in6 *sin6 = (struct sockaddr_in6 *)realaddr;
        sin6->sin6_family = AF_INET6;
        memcpy(&sin6->sin6_addr, header + 16, 16);
        memcpy(&sin6->sin6_port, header + 16 + 32, 2);
        *realaddrlen = sizeof(*sin6);
    }

    return 0;
}

/* Use the parsed peer metadata only for the accepted connection which
 * supplied it. Other connections retain the kernel socket address. */
void svr_get_remote_address(int sock, char **host, char **port, int numeric)
{
    if (qwrt_pp2_remoteaddr_active && qwrt_pp2_remoteaddr_sock == sock) {
        getaddrstring(&qwrt_pp2_remoteaddr, host, port, numeric);
    } else {
        get_socket_address(sock, NULL, NULL, host, port, numeric);
    }
}
'''

    replace_once(
        root / "src/svr-main.c",
        "static void commonsetup(void);\n",
        "static void commonsetup(void);\n" + main_helpers,
        MARKER,
    )

    accept_anchor = r'''			/* Limit the number of unauthenticated connections per IP */
			getaddrstring(&remoteaddr, &remote_host, NULL, 0);
'''
    accept_patch = r'''			/* Reset metadata inherited by this server process for each
			 * accepted connection. A forked child retains its own copy. */
			qwrt_pp2_remoteaddr_active = 0;
			qwrt_pp2_remoteaddr_sock = -1;
			memset(&qwrt_pp2_remoteaddr, 0, sizeof(qwrt_pp2_remoteaddr));

			/* Only the exact trusted Lucky address is allowed to send PPv2.
			 * It must send a valid header; malformed/missing headers are
			 * rejected rather than treated as an ordinary SSH connection. */
			if (qwrt_pp2_is_trusted_proxy(&remoteaddr)) {
				struct sockaddr_storage proxiedaddr;
				socklen_t proxiedlen = 0;

				if (qwrt_pp2_parse(childsock, &proxiedaddr, &proxiedlen) < 0) {
					dropbear_log(LOG_WARNING,
						"Rejecting connection from trusted proxy: invalid Proxy Protocol v2 header");
					goto out;
				}
				remoteaddr = proxiedaddr;
				remoteaddrlen = proxiedlen;
				qwrt_pp2_remoteaddr = proxiedaddr;
				qwrt_pp2_remoteaddr_sock = childsock;
				qwrt_pp2_remoteaddr_active = 1;
			}

			/* Limit the number of unauthenticated connections per IP using
			 * the real source address when this connection came through Lucky. */
			getaddrstring(&remoteaddr, &remote_host, NULL, 0);
'''
    replace_once(
        root / "src/svr-main.c",
        accept_anchor,
        accept_patch,
        "qwrt_pp2_parse(childsock, &proxiedaddr, &proxiedlen)",
    )

    replace_once(
        root / "src/session.h",
        "void svr_session(int sock, int childpipe) ATTRIB_NORETURN;\n",
        "void svr_session(int sock, int childpipe) ATTRIB_NORETURN;\n"
        "void svr_get_remote_address(int sock, char **host, char **port, int numeric);\n",
        "void svr_get_remote_address(int sock, char **host, char **port, int numeric);",
    )

    replace_once(
        root / "src/svr-session.c",
        "get_socket_address(ses.sock_in, NULL, NULL, &host, &port, 0);",
        "svr_get_remote_address(ses.sock_in, &host, &port, 0);",
        "svr_get_remote_address(ses.sock_in, &host, &port, 0);",
    )
    replace_once(
        root / "src/svr-session.c",
        "get_socket_address(ses.sock_in, NULL, NULL, \n\t\t\t&svr_ses.remotehost, NULL, 1);",
        "svr_get_remote_address(ses.sock_in, &svr_ses.remotehost, NULL, 1);",
        "svr_get_remote_address(ses.sock_in, &svr_ses.remotehost, NULL, 1);",
    )

    replace_once(
        root / "src/svr-chansession.c",
        "get_socket_address(ses.sock_in, &local_ip, &local_port, &remote_ip, &remote_port, 0);",
        "get_socket_address(ses.sock_in, &local_ip, &local_port, NULL, NULL, 0);\n"
        "\tsvr_get_remote_address(ses.sock_in, &remote_ip, &remote_port, 0);",
        "svr_get_remote_address(ses.sock_in, &remote_ip, &remote_port, 0);",
    )

    # ImmortalWrt's old 100-pubkey_path.patch predates upstream's
    # authorized_keys_filepath() refactor and no longer applies to Dropbear
    # 2026.91. Preserve its important behavior: root keys live in
    # /etc/dropbear/authorized_keys; non-root keys use the configured -D dir.
    replace_once(
        root / "src/svr-authpubkey.c",
        """\tconst char *filename = "authorized_keys";

\tdir = expand_homedir_path_home(svr_opts.authorized_keys_dir,
\t\t\t\t       ses.authstate.pw_dir);""",
        """\tconst char *filename = "authorized_keys";
\tconst char *key_dir = svr_opts.authorized_keys_dir;

\t/* QWRT root authorized_keys path: keep ImmortalWrt compatibility. */
\tif (ses.authstate.pw_uid == 0) {
\t\tkey_dir = "/etc/dropbear";
\t}
\tdir = expand_homedir_path_home(key_dir, ses.authstate.pw_dir);""",
        "QWRT root authorized_keys path",
    )

    # Fail closed if one of the required code paths was not changed.
    checks = {
        "src/svr-main.c": [
            "qwrt_pp2_is_trusted_proxy(&remoteaddr)",
            "qwrt_pp2_parse(childsock, &proxiedaddr, &proxiedlen)",
            "getaddrstring(&remoteaddr, &remote_host, NULL, 0)",
            MARKER,
        ],
        "src/svr-session.c": [
            "svr_get_remote_address(ses.sock_in, &host, &port, 0);",
            "svr_get_remote_address(ses.sock_in, &svr_ses.remotehost, NULL, 1);",
        ],
        "src/svr-chansession.c": [
            "svr_get_remote_address(ses.sock_in, &remote_ip, &remote_port, 0);",
        ],
        "src/session.h": [
            "void svr_get_remote_address(int sock, char **host, char **port, int numeric);",
        ],
        "src/svr-authpubkey.c": [
            "QWRT root authorized_keys path",
            'key_dir = "/etc/dropbear";',
        ],
    }
    for filename, markers in checks.items():
        text = (root / filename).read_text()
        for marker in markers:
            if marker not in text:
                raise SystemExit(f"Verification failed: {filename} lacks {marker!r}")

    print(f"Dropbear PPv2 patch verified in {root}")


if __name__ == "__main__":
    main()
