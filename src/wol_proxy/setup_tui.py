#!/usr/bin/env python3
import curses
import os
import re
import sys
from pathlib import Path
from typing import List

try:
    from .config import Config, save_config, DEFAULT_CONFIG_PATH
    from .arp_manager import IPManager
    from .util import log
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from wol_proxy.config import Config, save_config, DEFAULT_CONFIG_PATH
    from wol_proxy.arp_manager import IPManager
    from wol_proxy.util import log


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


FIELD_HELP = {
    "game_server_ip": "IPv4 address of the real game server (for example 192.168.1.50).",
    "game_server_mac": "MAC used for Wake-on-LAN. Use AA:BB:CC:DD:EE:FF (no quotes).",
    "net_cidr": "CIDR of the subnet. Press D to auto-detect after entering the IP.",
    "mc_port": "Minecraft TCP port exposed by the real server.",
    "mc_motd_idle": "Shown in the Minecraft server list while the server is offline.",
    "mc_motd_starting": "Shown right after a wake-up is triggered.",
    "mc_version_label": "Small line on the right of the server list entry.",
    "satisfactory_ports": "Comma separated UDP ports that should trigger Wake-on-LAN.",
    "ping_interval_sec": "Seconds between reachability checks while the server is online.",
    "ping_fail_threshold": "How many failed pings before taking the IP back.",
}


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

    has_colors = curses.has_colors()
    color_ids = {
        "background": 0,
        "selected": 0,
        "button": 0,
        "info": 0,
        "error": 0,
        "success": 0,
    }
    if has_colors:
        curses.start_color()
        try:
            curses.use_default_colors()
        except curses.error:
            pass
        curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLUE)
        curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_CYAN)
        curses.init_pair(3, curses.COLOR_WHITE, curses.COLOR_MAGENTA)
        curses.init_pair(4, curses.COLOR_YELLOW, curses.COLOR_BLUE)
        curses.init_pair(5, curses.COLOR_WHITE, curses.COLOR_RED)
        curses.init_pair(6, curses.COLOR_BLACK, curses.COLOR_GREEN)
        color_ids.update(
            {
                "background": 1,
                "selected": 2,
                "button": 3,
                "info": 4,
                "error": 5,
                "success": 6,
            }
        )

    def attr(name: str, extra: int = 0) -> int:
        pair = color_ids.get(name, 0)
        if not has_colors or pair == 0:
            return extra
        return curses.color_pair(pair) | extra

    stdscr.bkgd(" ", attr("background"))

    max_label = max(len(label) for _, label in FIELDS)
    col_value = 6 + max_label

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

    mode = "fields"
    field_index = 0
    action_index = 0
    status_msg = "Use Up/Down to select, Enter to edit, Tab for buttons."
    status_level = "info"
    actions = [
        ("save", "Save & Apply", "S"),
        ("cancel", "Cancel", "Q"),
    ]

    def set_status(message: str, level: str = "info") -> None:
        nonlocal status_msg, status_level
        status_msg = message
        status_level = level

    def draw() -> None:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        title = "WOL Proxy Setup"
        try:
            stdscr.addstr(0, max(0, (w - len(title)) // 2), title, attr("background", curses.A_BOLD) | curses.A_BOLD)
        except curses.error:
            pass
        controls = "Up/Down select | Enter edit | D auto CIDR | Tab buttons"
        try:
            stdscr.addstr(1, 2, controls[: max(0, w - 4)], attr("info", curses.A_DIM))
        except curses.error:
            pass

        for idx, (key, label) in enumerate(FIELDS):
            y = 3 + idx
            row_attr = attr("selected") if mode == "fields" and idx == field_index else attr("background")
            label_attr = row_attr | curses.A_BOLD
            value_attr = row_attr
            value = str(cfg.get(key, ""))
            if not value:
                value = "<required>"
            value = value[: max(0, w - col_value - 2)]
            try:
                stdscr.addstr(y, 2, f"{idx + 1:>2}. {label:<{max_label}}", label_attr)
                stdscr.addstr(y, col_value, value, value_attr)
            except curses.error:
                pass

        help_text = FIELD_HELP.get(FIELDS[field_index][0], "")
        try:
            stdscr.move(h - 6, 0)
            stdscr.clrtoeol()
            stdscr.addstr(h - 6, 2, help_text[: max(0, w - 4)], attr("info"))
        except curses.error:
            pass

        button_y = h - 4
        total_len = sum(len(f" {label} [{shortcut}] ") for _, label, shortcut in actions) + (len(actions) - 1) * 2
        start_x = max(2, (w - total_len) // 2)
        x = start_x
        for idx, (action_key, label, shortcut) in enumerate(actions):
            text = f"{label} [{shortcut}]"
            padded = f" {text} "
            attr_btn = attr("button", curses.A_BOLD)
            if mode == "actions" and idx == action_index:
                attr_btn = attr("selected", curses.A_BOLD)
            try:
                stdscr.addstr(button_y, x, padded[: max(0, w - x - 1)], attr_btn)
            except curses.error:
                pass
            x += len(padded) + 2

        status_attr = {
            "info": attr("info"),
            "error": attr("error"),
            "success": attr("success"),
        }.get(status_level, attr("info"))
        try:
            stdscr.move(h - 2, 0)
            stdscr.clrtoeol()
            stdscr.addstr(h - 2, 2, status_msg[: max(0, w - 4)], status_attr | curses.A_BOLD)
        except curses.error:
            pass

        stdscr.refresh()

    def edit_field(key: str, prompt: str) -> None:
        curses.curs_set(1)
        h, w = stdscr.getmaxyx()
        win_w = min(72, max(32, w - 6))
        win_h = 7
        win_y = max(2, (h - win_h) // 2)
        win_x = max(2, (w - win_w) // 2)
        win = curses.newwin(win_h, win_w, win_y, win_x)
        win.bkgd(" ", attr("background"))
        win.box()
        hint = FIELD_HELP.get(key, "")
        try:
            win.addstr(1, 2, prompt, curses.A_BOLD)
            if hint:
                win.addstr(2, 2, hint[: win_w - 4], attr("info"))
            win.addstr(3, 2, "Value:", curses.A_BOLD)
            win.addstr(4, 2, str(cfg.get(key, "")))
        except curses.error:
            pass
        win.refresh()
        curses.echo()
        try:
            win.move(4, 2)
            new_value = win.getstr(4, 2, win_w - 4).decode("utf-8").strip()
        except Exception:
            new_value = ""
        curses.noecho()
        curses.curs_set(0)
        if new_value:
            cfg[key] = new_value
            set_status(f"{prompt} updated.")
        else:
            set_status(f"{prompt} unchanged.")

    def handle_action(action: str):
        if action == "save":
            errors = _validate(cfg)
            if errors:
                set_status("; ".join(errors)[: 120], "error")
                return None
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
            set_status(f"Configuration saved to {DEFAULT_CONFIG_PATH}", "success")
            draw()
            curses.napms(700)
            return 0
        if action == "cancel":
            set_status("Setup cancelled. No changes written.")
            draw()
            curses.napms(400)
            return 1
        return None

    draw()
    while True:
        ch = stdscr.getch()
        if ch == curses.KEY_RESIZE:
            draw()
            continue
        if mode == "fields":
            if ch in (curses.KEY_UP, ord('k')):
                field_index = (field_index - 1) % len(FIELDS)
            elif ch in (curses.KEY_DOWN, ord('j')):
                field_index = (field_index + 1) % len(FIELDS)
            elif ch in (curses.KEY_ENTER, 10, 13):
                key, label = FIELDS[field_index]
                edit_field(key, label)
            elif ch in (9, ):  # Tab
                mode = "actions"
            elif ch in (ord('d'), ord('D')):
                ip = cfg.get("game_server_ip", "").strip()
                if ip:
                    cidr = _autodetect_cidr(ip)
                    if cidr:
                        cfg["net_cidr"] = str(cidr)
                        set_status(f"CIDR detected: /{cidr}", "success")
                    else:
                        set_status("CIDR auto-detect failed.", "error")
                else:
                    set_status("Set the game server IP before auto-detecting.", "error")
            elif ch in (ord('s'), ord('S')):
                result = handle_action("save")
                if result is not None:
                    return result
            elif ch in (ord('q'), ord('Q')):
                result = handle_action("cancel")
                if result is not None:
                    return result
        else:  # actions mode
            if ch in (curses.KEY_LEFT, ord('h')):
                action_index = (action_index - 1) % len(actions)
            elif ch in (curses.KEY_RIGHT, ord('l')):
                action_index = (action_index + 1) % len(actions)
            elif ch in (curses.KEY_ENTER, 10, 13):
                result = handle_action(actions[action_index][0])
                if result is not None:
                    return result
            elif ch in (9, curses.KEY_UP, ord('k')):
                mode = "fields"
            elif ch in (ord('s'), ord('S')):
                result = handle_action("save")
                if result is not None:
                    return result
            elif ch in (ord('q'), ord('Q')):
                result = handle_action("cancel")
                if result is not None:
                    return result
        draw()

def main():
    if os.geteuid() != 0:
        print("Please run as root (sudo).")
        return 1
    try:
        return curses.wrapper(run_tui)
    except curses.error:
        # Fallback auf einfache CLI Prompts
        print("Curses unavailable - switching to basic mode.")
        cfg = {}
        def ask(k, label, default):
            v = input(f"{label} [{default}]: ").strip()
            return v or default
        cfg["game_server_ip"] = ask("game_server_ip", "Game Server IP", "")
        cfg["game_server_mac"] = ask("game_server_mac", "Game Server MAC (AA:BB:CC:DD:EE:FF)", "AA:BB:CC:DD:EE:FF")
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


