import ipaddress
import re
from .util import log, sh


class IPManager:
    def __init__(self, target_ip: str, cidr: int | None = None):
        self.target_ip = target_ip
        self.cidr = cidr  # can be None -> auto detect
        self.iface = None
        self._claimed = False

    def detect_iface_and_cidr(self) -> tuple[str, int]:
        # Use `ip route get <ip>` to find interface and preferred src ip (and prefix length if available via route)
        rc, out, err = sh(["ip", "route", "get", self.target_ip])
        if rc != 0:
            raise RuntimeError(f"ip route get failed: {err}")
        # Example: '<ip> dev eth0 src 192.168.1.10 uid 0\n    cache \n'
        m = re.search(r"dev\s+(\S+)", out)
        if not m:
            raise RuntimeError(f"Failed to parse interface from: {out}")
        iface = m.group(1)
        if self.cidr is None:
            # Query CIDR for iface by parsing `ip -o -f inet addr show dev <iface>`
            rc2, out2, _ = sh(["ip", "-o", "-f", "inet", "addr", "show", "dev", iface])
            if rc2 != 0:
                raise RuntimeError("Failed to get iface addr info")
            # Line sample: '2: eth0    inet 192.168.1.10/24 brd 192.168.1.255 scope global eth0\n'
            m2 = re.search(r"inet\s+\S+/(\d+)", out2)
            if not m2:
                raise RuntimeError("Failed to parse CIDR")
            cidr = int(m2.group(1))
        else:
            cidr = self.cidr
        self.iface = iface
        self.cidr = cidr
        log(f"Detected iface={iface}, cidr=/{cidr}")
        return iface, cidr

    def claim_ip(self) -> None:
        if self._claimed:
            return
        if self.iface is None or self.cidr is None:
            self.detect_iface_and_cidr()
        # Add secondary IP address
        rc, _, err = sh(["ip", "addr", "add", f"{self.target_ip}/{self.cidr}", "dev", self.iface])
        if rc != 0:
            # If already exists, ignore
            if "File exists" not in err:
                raise RuntimeError(f"Failed to add IP: {err}")
        # Gratuitous ARP to update neighbors
        for _ in range(2):
            sh(["arping", "-U", "-I", self.iface, "-c", "1", self.target_ip])
        self._claimed = True
        log(f"Claimed IP {self.target_ip}/{self.cidr} on {self.iface}")

    def release_ip(self) -> None:
        if not self._claimed:
            return
        if self.iface is None or self.cidr is None:
            self.detect_iface_and_cidr()
        rc, _, err = sh(["ip", "addr", "del", f"{self.target_ip}/{self.cidr}", "dev", self.iface])
        if rc != 0:
            if "Cannot assign requested address" not in err and "Cannot find device" not in err:
                log(f"Warning: failed to delete IP: {err}")
        self._claimed = False
        log(f"Released IP {self.target_ip}/{self.cidr} from {self.iface}")

    @staticmethod
    def same_subnet(ip1: str, ip2: str, cidr: int) -> bool:
        net = ipaddress.ip_network(f"{ip1}/{cidr}", strict=False)
        return ipaddress.ip_address(ip2) in net

