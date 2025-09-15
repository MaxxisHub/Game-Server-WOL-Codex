import socket
from .util import log


def send_magic_packet(mac: str, broadcast: str = "255.255.255.255", port: int = 9) -> None:
    """Send a Wake-on-LAN magic packet to the given MAC."""
    mac = mac.replace("-", ":").lower()
    parts = mac.split(":")
    if len(parts) != 6 or not all(len(p) == 2 and all(c in "0123456789abcdef" for c in p) for p in parts):
        raise ValueError(f"Invalid MAC address: {mac}")
    hw = bytes(int(p, 16) for p in parts)
    pkt = b"\xff" * 6 + hw * 16
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.sendto(pkt, (broadcast, port))
    log(f"WOL magic packet sent to {mac} via {broadcast}:{port}")

