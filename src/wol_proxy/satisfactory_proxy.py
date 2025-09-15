import asyncio
from typing import Callable, List
from .util import log


class SatisfactoryProxy:
    def __init__(self, bind_ip: str, ports: List[int], on_query: Callable[[str], None]):
        self.bind_ip = bind_ip
        self.ports = ports
        self.on_query = on_query
        self._transports: list[asyncio.DatagramTransport] = []

    async def start(self):
        loop = asyncio.get_running_loop()
        for p in self.ports:
            transport, protocol = await loop.create_datagram_endpoint(
                lambda: _UDPHandler(self.on_query), local_addr=(self.bind_ip, p)
            )
            self._transports.append(transport)
            log(f"Satisfactory proxy listening on {self.bind_ip}:{p}/udp")

    async def stop(self):
        for t in self._transports:
            try:
                t.close()
            except Exception:
                pass
        self._transports.clear()
        log("Satisfactory proxy stopped")


class _UDPHandler(asyncio.DatagramProtocol):
    def __init__(self, on_query):
        self.on_query = on_query

    def datagram_received(self, data: bytes, addr):
        self.on_query(f"udp from {addr}")
        # We do not respond; only trigger.

