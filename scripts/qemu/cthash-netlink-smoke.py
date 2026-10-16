#!/usr/bin/env python3
"""Exercise the private cthash ipset type through its kernel netlink ABI.

The stock ipset userspace library only registers upstream type names, so it
cannot parse ``cthash:ip,port`` even when the out-of-tree kernel type is
registered.  Send the same nfnetlink messages directly to distinguish that
userspace limitation from a kernel registration or ABI failure.
"""

import errno
import socket
import struct


NETLINK_NETFILTER = 12
NFNL_SUBSYS_IPSET = 6
NFNETLINK_V0 = 0

NLM_F_REQUEST = 0x001
NLM_F_ACK = 0x004
NLM_F_EXCL = 0x200
NLM_F_CREATE = 0x400
NLMSG_ERROR = 0x2

NLA_F_NESTED = 1 << 15
NLA_F_NET_BYTEORDER = 1 << 14

IPSET_PROTOCOL = 7
IPSET_CMD_CREATE = 2
IPSET_CMD_DESTROY = 3
IPSET_CMD_ADD = 9
IPSET_CMD_TEST = 11

IPSET_ATTR_PROTOCOL = 1
IPSET_ATTR_SETNAME = 2
IPSET_ATTR_TYPENAME = 3
IPSET_ATTR_REVISION = 4
IPSET_ATTR_FAMILY = 5
IPSET_ATTR_DATA = 7

IPSET_ATTR_IP = 1
IPSET_ATTR_PORT = 4
IPSET_ATTR_PROTO = 7
IPSET_ATTR_IPADDR_IPV4 = 1

SET_NAME = "qemu-cthash"
TYPE_NAME = "cthash:ip,port"


def align4(length):
    return (length + 3) & ~3


def attr(attr_type, payload=b""):
    length = 4 + len(payload)
    return struct.pack("HH", length, attr_type) + payload + b"\0" * (align4(length) - length)


class IpSetNetlink:
    def __init__(self):
        self.sock = socket.socket(socket.AF_NETLINK, socket.SOCK_RAW,
                                  NETLINK_NETFILTER)
        self.sock.bind((0, 0))
        self.portid = self.sock.getsockname()[0]
        self.sequence = 0

    def command(self, command, attributes, *, create=False):
        self.sequence += 1
        flags = NLM_F_REQUEST | NLM_F_ACK | NLM_F_EXCL
        if create:
            flags |= NLM_F_CREATE
        payload = struct.pack("!BBH", socket.AF_INET, NFNETLINK_V0, 0)
        payload += b"".join(attributes)
        length = 16 + len(payload)
        header = struct.pack("IHHII", length,
                             (NFNL_SUBSYS_IPSET << 8) | command,
                             flags, self.sequence, self.portid)
        self.sock.send(header + payload)

        while True:
            response = self.sock.recv(65535)
            offset = 0
            while offset + 16 <= len(response):
                msg_len, msg_type, _, sequence, _ = struct.unpack_from(
                    "IHHII", response, offset)
                if msg_len < 16:
                    raise RuntimeError("invalid netlink response length")
                if sequence == self.sequence and msg_type == NLMSG_ERROR:
                    error = struct.unpack_from("i", response, offset + 16)[0]
                    if error:
                        raise OSError(-error, errno.errorcode.get(-error,
                                                                 "ipset error"))
                    return
                offset += align4(msg_len)


def string_attr(attr_type, value):
    return attr(attr_type, value.encode() + b"\0")


def common_attrs():
    return [attr(IPSET_ATTR_PROTOCOL, bytes([IPSET_PROTOCOL])),
            string_attr(IPSET_ATTR_SETNAME, SET_NAME)]


def element_attrs(address, port, protocol):
    ip = attr(IPSET_ATTR_IPADDR_IPV4 | NLA_F_NET_BYTEORDER,
              socket.inet_aton(address))
    return attr(IPSET_ATTR_DATA | NLA_F_NESTED,
                attr(IPSET_ATTR_IP | NLA_F_NESTED, ip)
                + attr(IPSET_ATTR_PORT | NLA_F_NET_BYTEORDER,
                       struct.pack("!H", port))
                + attr(IPSET_ATTR_PROTO, bytes([protocol])))


def main():
    netlink = IpSetNetlink()
    created = False
    try:
        netlink.command(
            IPSET_CMD_CREATE,
            common_attrs()
            + [string_attr(IPSET_ATTR_TYPENAME, TYPE_NAME),
               attr(IPSET_ATTR_REVISION, b"\x05"),
               attr(IPSET_ATTR_FAMILY, bytes([socket.AF_INET])),
               attr(IPSET_ATTR_DATA | NLA_F_NESTED)],
            create=True)
        created = True

        element = element_attrs("198.51.100.42", 443, socket.IPPROTO_TCP)
        netlink.command(IPSET_CMD_ADD, common_attrs() + [element])
        netlink.command(IPSET_CMD_TEST, common_attrs() + [element])
        print(f"created {SET_NAME} ({TYPE_NAME}) and verified IPv4 TCP member")
    finally:
        if created:
            netlink.command(IPSET_CMD_DESTROY, common_attrs())


if __name__ == "__main__":
    main()
