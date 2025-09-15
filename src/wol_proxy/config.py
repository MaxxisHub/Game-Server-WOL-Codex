import json
import os
from dataclasses import dataclass, asdict
from typing import Optional, List


DEFAULT_CONFIG_PATH = "/opt/wol-proxy/config.json"


@dataclass
class Config:
    game_server_ip: str
    game_server_mac: str
    net_cidr: int = 24
    mc_port: int = 25565
    mc_motd_idle: str = "Join to start Server"
    mc_motd_starting: str = "Starting..."
    mc_version_label: str = "Offline"
    satisfactory_ports: List[int] = None
    ping_interval_sec: int = 3
    ping_fail_threshold: int = 10

    def __post_init__(self):
        if self.satisfactory_ports is None:
            self.satisfactory_ports = [15000, 15777, 7777]


def load_config(path: Optional[str] = None) -> Optional[Config]:
    cfg_path = path or DEFAULT_CONFIG_PATH
    if not os.path.exists(cfg_path):
        return None
    with open(cfg_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return Config(**data)


def save_config(cfg: Config, path: Optional[str] = None) -> None:
    cfg_path = path or DEFAULT_CONFIG_PATH
    os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(asdict(cfg), f, indent=2, ensure_ascii=False)

