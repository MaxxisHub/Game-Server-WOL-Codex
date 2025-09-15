#!/usr/bin/env python3
import curses
import os
import re
import sys
from typing import List

from .config import Config, save_config, DEFAULT_CONFIG_PATH
from .arp_manager import IPManager
from .util import log


FIELDS = [
    ("game_server_ip", "Game Server IP"),
    ("game_server_mac", "Game Server MAC"),
    ("net_cidr", "Netzwerk CIDR (/24)"),
    ("mc_port", "Minecraft Port"),
    ("mc_motd_idle", "MC MOTD (idle)"),
    ("mc_motd_starting", "MC MOTD (starting)"),
    ("mc_version_label", "MC Version Label (rechts)"),
    ("satisfactory_ports", "Satisfactory Ports (CSV)"),
    ("ping_interval_sec", "Ping Intervall (Sekunden)"),
    ("ping_fail_threshold", "Ping Fail Threshold"),
]


def _validate(cfg: dict) -> List[str]:
    errors = []
    ip_re = re.compile(r"^(\d{1,3}\.){3}\d{1,3}$")
    mac_re = re.compile(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$")
    if not ip_re.match(cfg["game_server_ip"]):
        errors.append("Ungültige IP-Adresse")
    if not mac_re.match(cfg["game_server_mac"]):
        errors.append("Ungültige MAC-Adresse (Format AA:BB:CC:DD:EE:FF)")
    try:
        cidr = int(cfg["net_cidr"])
        if not (8 <= cidr <= 32):
            errors.append("CIDR muss zwischen 8 und 32 liegen")
    except Exception:
        errors.append("CIDR muss eine Zahl sein")
    try:
        mp = int(cfg["mc_port"])
        if not (1 <= mp <= 65535):
            errors.append("Minecraft Port ungültig")
    except Exception:
        errors.append("Minecraft Port muss eine Zahl sein")
    try:
        cfg["_sf_ports_list"] = [int(p.strip()) for p in str(cfg["satisfactory_ports"]).split(',') if p.strip()]
        if not cfg["_sf_ports_list"]:
            errors.append("Mindestens ein Satisfactory Port angeben")
        for p in cfg["_sf_ports_list"]:
            if not (1 <= p <= 65535):
                errors.append("Satisfactory Ports enthalten ungültige Werte")
                break
    except Exception:
        errors.append("Satisfactory Ports: kommaseparierte Zahlen")
    for key in ("ping_interval_sec", "ping_fail_threshold"):
        try:
            v = int(cfg[key])
            if v <= 0:
                errors.append(f"{key} muss > 0 sein")
        except Exception:
            errors.append(f"{key} muss eine Zahl sein")
    return errors


def _autodetect_cidr(ip: str) -> int | None:
    try:
        ipm = IPManager(ip, None)
        _, cidr = ipm.detect_iface_and_cidr()
        return cidr
    except Exception:
        return None


def run_tui(stdscr):
    curses.curs_set(0)
    stdscr.nodelay(False)
    stdscr.keypad(True)

    # Default values
    cfg = {
        "game_server_ip": "",
        "game_server_mac": "",
        "net_cidr": "24",
        "mc_port": "25565",
        "mc_motd_idle": "Join to start Server",
        "mc_motd_starting": "Starting...",
        "mc_version_label": "Offline",
        "satisfactory_ports": "15000,15777,7777",
        "ping_interval_sec": "3",
        "ping_fail_threshold": "10",
    }

    sel = 0
    msg = "↑/↓ wählen, Enter bearbeiten, D: CIDR auto, S: Speichern, Q: Abbruch"

    def draw():
        stdscr.clear()
        h, w = stdscr.getmaxyx()
        title = "WOL Proxy – Terminal Setup"
        stdscr.addstr(0, max(0, (w - len(title)) // 2), title, curses.A_BOLD)
        col1 = 2
        col2 = 30
        for i, (key, label) in enumerate(FIELDS):
            y = 2 + i
            attr = curses.A_REVERSE if i == sel else curses.A_NORMAL
            stdscr.addstr(y, col1, f"{label}: ", attr)
            val = str(cfg[key])
            maxlen = max(10, w - col2 - 2)
            if len(val) > maxlen:
                val = val[:maxlen-3] + "..."
            stdscr.addstr(y, col2, val, attr)
        stdscr.addstr(h-2, 2, msg[: max(0, w-4)])
        stdscr.refresh()

    def edit_field(key, prompt):
        nonlocal msg
        curses.curs_set(1)
        h, w = stdscr.getmaxyx()
        win_w = min(70, w - 4)
        win_h = 5
        win_y = max(1, (h - win_h) // 2)
        win_x = max(2, (w - win_w) // 2)
        win = curses.newwin(win_h, win_w, win_y, win_x)
        win.border()
        win.addstr(1, 2, f"{prompt}:")
        win.addstr(2, 2, str(cfg[key]))
        win.refresh()
        curses.echo()
        win.move(2, 2)
        val = win.getstr(2, 2, win_w - 4).decode("utf-8")
        curses.noecho()
        curses.curs_set(0)
        cfg[key] = val.strip()
        msg = "Wert aktualisiert"

    while True:
        draw()
        ch = stdscr.getch()
        if ch in (curses.KEY_UP, ord('k')):
            sel = (sel - 1) % len(FIELDS)
        elif ch in (curses.KEY_DOWN, ord('j')):
            sel = (sel + 1) % len(FIELDS)
        elif ch in (curses.KEY_ENTER, 10, 13):
            key, label = FIELDS[sel]
            edit_field(key, label)
        elif ch in (ord('d'), ord('D')):
            ip = cfg.get("game_server_ip", "").strip()
            if ip:
                cidr = _autodetect_cidr(ip)
                if cidr:
                    cfg["net_cidr"] = str(cidr)
                    msg = f"CIDR automatisch erkannt: /{cidr}"
                else:
                    msg = "CIDR konnte nicht automatisch erkannt werden"
            else:
                msg = "Bitte zuerst Game Server IP setzen"
        elif ch in (ord('s'), ord('S')):
            errs = _validate(cfg)
            if errs:
                msg = "; ".join(errs)[:80]
            else:
                # Finalize config dataclass
                conf = Config(
                    game_server_ip=cfg["game_server_ip"],
                    game_server_mac=cfg["game_server_mac"],
                    net_cidr=int(cfg["net_cidr"]),
                    mc_port=int(cfg["mc_port"]),
                    mc_motd_idle=cfg["mc_motd_idle"],
                    mc_motd_starting=cfg["mc_motd_starting"],
                    mc_version_label=cfg["mc_version_label"],
                    satisfactory_ports=cfg["_sf_ports_list"],
                    ping_interval_sec=int(cfg["ping_interval_sec"]),
                    ping_fail_threshold=int(cfg["ping_fail_threshold"]),
                )
                save_config(conf, DEFAULT_CONFIG_PATH)
                msg = f"Konfiguration gespeichert nach {DEFAULT_CONFIG_PATH}"
                draw()
                curses.napms(600)
                return 0
        elif ch in (ord('q'), ord('Q')):
            return 1


def main():
    if os.geteuid() != 0:
        print("Bitte mit sudo/root ausführen.")
        return 1
    try:
        return curses.wrapper(run_tui)
    except curses.error:
        # Fallback auf einfache CLI Prompts
        print("Curses nicht verfügbar – einfacher Modus.")
        cfg = {}
        def ask(k, label, default):
            v = input(f"{label} [{default}]: ").strip()
            return v or default
        cfg["game_server_ip"] = ask("game_server_ip", "Game Server IP", "")
        cfg["game_server_mac"] = ask("game_server_mac", "Game Server MAC", "")
        cidr = _autodetect_cidr(cfg["game_server_ip"]) or 24
        cfg["net_cidr"] = ask("net_cidr", "Netzwerk CIDR", str(cidr))
        cfg["mc_port"] = ask("mc_port", "Minecraft Port", "25565")
        cfg["mc_motd_idle"] = ask("mc_motd_idle", "MC MOTD (idle)", "Join to start Server")
        cfg["mc_motd_starting"] = ask("mc_motd_starting", "MC MOTD (starting)", "Starting...")
        cfg["mc_version_label"] = ask("mc_version_label", "MC Version Label", "Offline")
        cfg["satisfactory_ports"] = ask("satisfactory_ports", "Satisfactory Ports (CSV)", "15000,15777,7777")
        cfg["ping_interval_sec"] = ask("ping_interval_sec", "Ping Intervall", "3")
        cfg["ping_fail_threshold"] = ask("ping_fail_threshold", "Ping Fail Threshold", "10")
        errs = _validate(cfg)
        if errs:
            print("Fehler:", "; ".join(errs))
            return 1
        conf = Config(
            game_server_ip=cfg["game_server_ip"],
            game_server_mac=cfg["game_server_mac"],
            net_cidr=int(cfg["net_cidr"]),
            mc_port=int(cfg["mc_port"]),
            mc_motd_idle=cfg["mc_motd_idle"],
            mc_motd_starting=cfg["mc_motd_starting"],
            mc_version_label=cfg["mc_version_label"],
            satisfactory_ports=[int(p) for p in cfg["satisfactory_ports"].split(',') if p.strip()],
            ping_interval_sec=int(cfg["ping_interval_sec"]),
            ping_fail_threshold=int(cfg["ping_fail_threshold"]),
        )
        save_config(conf, DEFAULT_CONFIG_PATH)
        print(f"Gespeichert: {DEFAULT_CONFIG_PATH}")
        return 0


if __name__ == "__main__":
    sys.exit(main())

