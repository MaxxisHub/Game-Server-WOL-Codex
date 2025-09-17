import ipaddress
import re
from typing import List

from .util import log, sh


class IPManager:
    def __init__(self, target_ip: str, cidr: int | None = None):
        self.target_ip = target_ip
        self.cidr = cidr
        self.iface: str | None = None
        self.broadcasts: List[str] = []
        self._claimed = False

    def detect_iface_and_cidr(self) -> tuple[str, int]:
        rc, out, err = sh(["ip", "route", "get", self.target_ip])
        if rc != 0:
            raise RuntimeError(f"ip route get failed: {err}")
        match = re.search(r"dev\s+(\S+)", out)
        if not match:
            raise RuntimeError(f"Failed to parse interface from: {out}")
        iface = match.group(1)

        rc2, out2, err2 = sh(["ip", "-o", "-f", "inet", "addr", "show", "dev", iface])
        if rc2 != 0:
            raise RuntimeError(f"Failed to get iface addr info: {err2}")

        detected_cidr: int | None = None
        broadcast_candidates: List[str] = []
        for line in out2.splitlines():
            addr_match = re.search(r"inet\s+\S+/(\d+)", line)
            if addr_match and detected_cidr is None:
                detected_cidr = int(addr_match.group(1))
            brd_match = re.search(r"brd\s+(\S+)", line)
            if brd_match:
                broadcast_candidates.append(brd_match.group(1))

        if self.cidr is None:
            if detected_cidr is None:
                raise RuntimeError("Failed to determine CIDR for interface")
            cidr = detected_cidr
        else:
            cidr = self.cidr

        if not broadcast_candidates:
            try:
                network = ipaddress.ip_network(f"{self.target_ip}/{cidr}", strict=False)
                broadcast_candidates.append(str(network.broadcast_address))
            except Exception:
                pass

        self.iface = iface
        self.cidr = cidr
        self.broadcasts = broadcast_candidates
        log(f"Detected iface={iface}, cidr=/{cidr}, broadcasts={broadcast_candidates}")
        return iface, cidr

    def claim_ip(self) -> None:
        if self._claimed:
            return
        if self.iface is None or self.cidr is None:
            self.detect_iface_and_cidr()
        rc, _, err = sh(["ip", "addr", "add", f"{self.target_ip}/{self.cidr}", "dev", self.iface])
        if rc != 0 and "File exists" not in err:
            raise RuntimeError(f"Failed to add IP: {err}")
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
        if rc != 0 and "Cannot assign requested address" not in err and "Cannot find device" not in err:
            log(f"Warning: failed to delete IP: {err}")
        self._claimed = False
        log(f"Released IP {self.target_ip}/{self.cidr} from {self.iface}")

    def get_broadcasts(self) -> List[str]:
        if not self.broadcasts:
            if self.iface is None or self.cidr is None:
                self.detect_iface_and_cidr()
            else:
                try:
                    network = ipaddress.ip_network(f"{self.target_ip}/{self.cidr}", strict=False)
                    self.broadcasts = [str(network.broadcast_address)]
                except Exception:
                    self.broadcasts = []
        return self.broadcasts

    @staticmethod
    def same_subnet(ip1: str, ip2: str, cidr: int) -> bool:
        net = ipaddress.ip_network(f"{ip1}/{cidr}", strict=False)
        return ipaddress.ip_address(ip2) in net
