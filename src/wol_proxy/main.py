import argparse
import asyncio
import os
from pathlib import Path
 

try:
    from .arp_manager import IPManager
    from .config import Config, load_config, save_config, DEFAULT_CONFIG_PATH
    from .mc_proxy import MCProxy
    from .satisfactory_proxy import SatisfactoryProxy
    from .util import log, ping_host
    from .wol import send_magic_packet
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from wol_proxy.arp_manager import IPManager
    from wol_proxy.config import Config, load_config, save_config, DEFAULT_CONFIG_PATH
    from wol_proxy.mc_proxy import MCProxy
    from wol_proxy.satisfactory_proxy import SatisfactoryProxy
    from wol_proxy.util import log, ping_host
    from wol_proxy.wol import send_magic_packet


"""
Daemon wartet, wenn keine Konfiguration vorhanden ist. Für Ersteinrichtung:
sudo wol-proxy-setup
"""


class ProxyManager:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.ipm = IPManager(cfg.game_server_ip, cfg.net_cidr)
        self.mc_proxy: MCProxy | None = None
        self.sf_proxy: SatisfactoryProxy | None = None
        self.state = "INIT"  # INIT -> OFFLINE -> STARTING -> ONLINE
        self._motd_state = "idle"  # idle | starting
        self._starting_since = None
        self._fail_count = 0
        self._ok_count = 0

    async def run(self):
        # main loop
        while True:
            try:
                up = self._is_server_up()
                if up:
                    self._ok_count += 1
                    self._fail_count = 0
                    await self._ensure_released()
                    if self.state != "ONLINE":
                        log("State ONLINE (real server reachable)")
                        self.state = "ONLINE"
                        self._motd_state = "idle"
                else:
                    self._fail_count += 1
                    self._ok_count = 0
                    # Server seems down (only act after threshold to avoid flapping)
                    if self._fail_count >= max(1, self.cfg.ping_fail_threshold):
                        if self.state != "STARTING":
                            await self._ensure_claimed_and_listening()
                            if self.state != "OFFLINE":
                                log("State OFFLINE (proxy active)")
                                self.state = "OFFLINE"
                        else:
                            # STARTING: Wait until server becomes reachable
                            pass
            except Exception as e:
                log(f"Main loop error: {e}")
            await asyncio.sleep(self.cfg.ping_interval_sec)

    def _is_server_up(self) -> bool:
        # Prefer ping
        return ping_host(self.cfg.game_server_ip, timeout_sec=max(1, self.cfg.ping_interval_sec))

    async def _ensure_released(self):
        # stop proxies, release IP
        if self.mc_proxy is not None:
            await self.mc_proxy.stop()
            self.mc_proxy = None
        if self.sf_proxy is not None:
            await self.sf_proxy.stop()
            self.sf_proxy = None
        self.ipm.release_ip()

    async def _ensure_claimed_and_listening(self):
        self.ipm.claim_ip()
        # Start proxies if not running
        if self.mc_proxy is None:
            self.mc_proxy = MCProxy(
                bind_ip=self.cfg.game_server_ip,
                port=self.cfg.mc_port,
                get_status=self._mc_status,
                on_join_attempt=self._on_mc_join,
            )
            await self.mc_proxy.start()
        if self.sf_proxy is None:
            self.sf_proxy = SatisfactoryProxy(
                bind_ip=self.cfg.game_server_ip,
                ports=self.cfg.satisfactory_ports,
                on_query=self._on_sf_query,
            )
            await self.sf_proxy.start()

    def _mc_status(self, client_proto: int) -> dict:
        version_label = self.cfg.mc_version_label
        if self._motd_state == "starting":
            motd = self.cfg.mc_motd_starting
        else:
            motd = self.cfg.mc_motd_idle
        # Reflect client protocol to avoid incompatibility marker
        proto = client_proto
        return {
            "version": {"name": version_label, "protocol": proto},
            "players": {"max": 0, "online": 0},
            "description": {"text": motd},
        }

    def _trigger_start(self, reason: str):
        log(f"Start trigger: {reason}")
        broadcasts = []
        try:
            broadcasts.extend(self.ipm.get_broadcasts())
        except Exception as e:
            log(f"Failed to determine broadcast addresses: {e}")
        broadcasts.append("255.255.255.255")
        seen = set()
        for addr in broadcasts:
            if not addr or addr in seen:
                continue
            seen.add(addr)
            try:
                send_magic_packet(self.cfg.game_server_mac, broadcast=addr)
            except Exception as exc:
                log(f"WOL error via {addr}: {exc}")
        self._motd_state = "starting"
        self.state = "STARTING"
        # Release IP and stop listeners immediately to free the ports
        # Schedule on current loop
        loop = asyncio.get_running_loop()
        loop.create_task(self._ensure_released())

    def _on_mc_join(self, info: str):
        self._trigger_start(f"MC join attempt ({info})")

    def _on_sf_query(self, info: str):
        # Trigger as soon as server browser queries these ports
        if self.state != "STARTING":
            self._trigger_start(f"Satisfactory discovery ({info})")


async def main_async(args):
    cfg = load_config(args.config)
    if not cfg:
        log("Keine Konfiguration gefunden. Bitte 'sudo wol-proxy-setup' ausführen.")
        while not os.path.exists(DEFAULT_CONFIG_PATH):
            await asyncio.sleep(1)
        cfg = load_config(args.config)
        log("Konfiguration geladen.")

    # Ensure IP manager knows iface/cidr
    pm = ProxyManager(cfg)

    # When running in foreground, just run the loop; in daemon mode, same behavior
    await pm.run()


def parse_args():
    p = argparse.ArgumentParser(description="WOL Proxy (Minecraft & Satisfactory)")
    p.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="Pfad zur config.json")
    p.add_argument("--daemon", action="store_true", help="als Dienst laufen (default)")
    p.add_argument("--foreground", action="store_true", help="im Vordergrund laufen (Debug)")
    return p.parse_args()


def main():
    args = parse_args()
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
