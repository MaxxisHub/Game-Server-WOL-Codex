#!/usr/bin/env python3
import curses
import os
import re
import subprocess
import sys
from pathlib import Path
from textwrap import wrap
from typing import List, Tuple

try:
    from .config import (
        Config,
        DEFAULT_CONFIG_PATH,
        load_config,
        save_config,
    )
    from .arp_manager import IPManager
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from wol_proxy.config import (
        Config,
        DEFAULT_CONFIG_PATH,
        load_config,
        save_config,
    )
    from wol_proxy.arp_manager import IPManager


FIELDS = [
    ("game_server_ip", "Game Server IP"),
    ("game_server_mac", "Game Server MAC"),
    ("net_cidr", "Network CIDR (/24)"),
    ("mc_port", "Minecraft Port"),
    ("mc_motd_idle", "Minecraft MOTD (idle)"),
    ("mc_motd_starting", "Minecraft MOTD (starting)"),
    ("mc_version_label", "Minecraft Version Label"),
    ("satisfactory_ports", "Satisfactory Ports (CSV)"),
    ("ping_interval_sec", "Ping Interval (sec)"),
    ("ping_fail_threshold", "Ping Fail Threshold"),
]


FIELD_HELP = {
    "game_server_ip": "IPv4 address of the real game server (example 192.168.1.50).",
    "game_server_mac": "MAC used for Wake-on-LAN. Use AA:BB:CC:DD:EE:FF without quotes.",
    "net_cidr": "Subnet size in CIDR notation. Press D to auto-detect after entering the IP.",
    "mc_port": "Minecraft TCP port exposed by the real server.",
    "mc_motd_idle": "Shown in the Minecraft server list while the real server is offline.",
    "mc_motd_starting": "Shown right after a wake-up is triggered.",
    "mc_version_label": "Small label on the right in the Minecraft server list.",
    "satisfactory_ports": "Comma separated UDP ports that should trigger Wake-on-LAN.",
    "ping_interval_sec": "Seconds between reachability checks while the server is online.",
    "ping_fail_threshold": "How many failed pings before the proxy takes over again.",
}


DEFAULT_FIELD_VALUES = {
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


def _config_to_fields(conf: Config) -> dict:
    return {
        "game_server_ip": conf.game_server_ip,
        "game_server_mac": conf.game_server_mac,
        "net_cidr": str(conf.net_cidr),
        "mc_port": str(conf.mc_port),
        "mc_motd_idle": conf.mc_motd_idle,
        "mc_motd_starting": conf.mc_motd_starting,
        "mc_version_label": conf.mc_version_label,
        "satisfactory_ports": ",".join(str(port) for port in conf.satisfactory_ports),
        "ping_interval_sec": str(conf.ping_interval_sec),
        "ping_fail_threshold": str(conf.ping_fail_threshold),
    }


def _initial_field_values() -> Tuple[dict, bool]:
    values = DEFAULT_FIELD_VALUES.copy()
    existing = load_config()
    if existing:
        values.update(_config_to_fields(existing))
        return values, True
    return values, False


def _run_post_install_checks() -> List[Tuple[str, str, str]]:
    checks: List[Tuple[str, str, str]] = []
    commands = [
        ("Service active", ["systemctl", "is-active", "wol-proxy"], True),
        ("Service enabled", ["systemctl", "is-enabled", "wol-proxy"], True),
        ("Recent logs", ["journalctl", "-u", "wol-proxy", "-n", "5", "--no-pager"], False),
    ]
    for label, cmd, expect_success in commands:
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=6,
                check=False,
            )
        except FileNotFoundError:
            checks.append((label, "error", f"Command not available: {' '.join(cmd)}"))
            continue
        except subprocess.TimeoutExpired:
            checks.append((label, "error", f"Timeout while running: {' '.join(cmd)}"))
            continue

        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()

        if expect_success:
            if result.returncode == 0:
                checks.append((label, "success", stdout or "OK"))
            else:
                checks.append((label, "error", stderr or stdout or f"Exit code {result.returncode}"))
        else:
            if result.returncode == 0:
                checks.append((label, "info", stdout or "No recent log entries."))
            else:
                checks.append((label, "error", stderr or stdout or f"Exit code {result.returncode}"))
    return checks


def _validate(cfg: dict) -> List[str]:
    errors: List[str] = []
    ip_re = re.compile(r"^(\d{1,3}\.){3}\d{1,3}$")
    mac_re = re.compile(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$")
    if not ip_re.match(cfg["game_server_ip"]):
        errors.append("Invalid IP address")
    if not mac_re.match(cfg["game_server_mac"]):
        errors.append("Invalid MAC address (use AA:BB:CC:DD:EE:FF)")
    try:
        cidr = int(cfg["net_cidr"])
        if not (8 <= cidr <= 32):
            errors.append("CIDR must be between 8 and 32")
    except Exception:
        errors.append("CIDR must be a number")
    try:
        mc_port = int(cfg["mc_port"])
        if not (1 <= mc_port <= 65535):
            errors.append("Minecraft port is out of range")
    except Exception:
        errors.append("Minecraft port must be a number")
    try:
        cfg["_sf_ports_list"] = [
            int(port.strip())
            for port in str(cfg["satisfactory_ports"]).split(',')
            if port.strip()
        ]
        if not cfg["_sf_ports_list"]:
            errors.append("Provide at least one Satisfactory port")
        for port in cfg["_sf_ports_list"]:
            if not (1 <= port <= 65535):
                errors.append("Satisfactory ports contain invalid values")
                break
    except Exception:
        errors.append("Satisfactory ports must be comma separated numbers")
    for field in ("ping_interval_sec", "ping_fail_threshold"):
        try:
            value = int(cfg[field])
            if value <= 0:
                errors.append(f"{field} must be greater than zero")
        except Exception:
            errors.append(f"{field} must be a number")
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
    color_pairs = {
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
        curses.init_pair(3, curses.COLOR_WHITE, curses.COLOR_BLUE)
        curses.init_pair(4, curses.COLOR_YELLOW, curses.COLOR_BLUE)
        curses.init_pair(5, curses.COLOR_WHITE, curses.COLOR_RED)
        curses.init_pair(6, curses.COLOR_BLACK, curses.COLOR_GREEN)
        color_pairs.update(
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
        pair = color_pairs.get(name, 0)
        if not has_colors or pair == 0:
            return extra
        return curses.color_pair(pair) | extra

    stdscr.bkgd(' ', attr("background"))
    stdscr.erase()

    max_label_len = max(len(label) for _, label in FIELDS)
    value_col = 6 + max_label_len

    cfg, loaded_existing = _initial_field_values()

    mode = "fields"
    field_index = 0
    action_index = 0
    status_msg = "Loaded existing configuration. Adjust values and press Save." if loaded_existing else "Up/Down select, Enter edit, Tab switches to buttons."
    status_level = "info"
    actions = [
        ("save", "Save & Apply", "S"),
        ("cancel", "Cancel", "Q"),
    ]

    def set_status(message: str, level: str = "info") -> None:
        nonlocal status_msg, status_level
        status_msg = message
        status_level = level

    def draw_border(win: curses.window) -> None:
        win.border('|', '|', '-', '-', '+', '+', '+', '+')

    def show_summary(title: str, items: List[Tuple[str, str, str]]) -> None:
        if not items:
            return
        h, w = stdscr.getmaxyx()
        lines: List[Tuple[str, str]] = []
        for label, level, message in items:
            payload = message.splitlines() or [""]
            lines.append((level, f"[{label}] {payload[0]}"))
            for extra in payload[1:]:
                lines.append((level, f"    {extra}"))
        body_width = max(len(text) for _, text in lines) if lines else len(title)
        win_w = min(max(body_width + 4, len(title) + 4, 44), max(60, w - 4))
        win_h = min(len(lines) + 6, max(12, h - 4))
        win_y = max(1, (h - win_h) // 2)
        win_x = max(2, (w - win_w) // 2)
        win = curses.newwin(win_h, win_w, win_y, win_x)
        win.bkgd(' ', attr("background"))
        win.erase()
        draw_border(win)
        try:
            win.addstr(1, max(2, (win_w - len(title)) // 2), title, attr("button", curses.A_BOLD))
        except curses.error:
            pass
        y = 3
        for level, text_line in lines[: win_h - 5]:
            try:
                win.addstr(y, 2, text_line[: win_w - 4], attr(level))
            except curses.error:
                pass
            y += 1
        footer = "Press any key to continue"
        try:
            win.addstr(win_h - 2, 2, footer[: win_w - 4], attr("info", curses.A_DIM))
        except curses.error:
            pass
        win.refresh()
        win.getch()
        win.clear()
        stdscr.touchwin()

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
            value = str(cfg.get(key, "")) or "<required>"
            value = value[: max(0, w - value_col - 2)]
            try:
                stdscr.addstr(y, 2, f"{idx + 1:>2}. {label:<{max_label_len}}", label_attr)
                stdscr.addstr(y, value_col, value, value_attr)
            except curses.error:
                pass

        help_text = FIELD_HELP.get(FIELDS[field_index][0], "")
        for offset, line in enumerate(wrap(help_text, max(20, w - 4))[:2]):
            try:
                stdscr.addstr(3 + len(FIELDS) + offset, 2, line, attr("info"))
            except curses.error:
                pass

        button_y = max(len(FIELDS) + 6, h - 4)
        total_button_len = sum(len(f" {label} [{shortcut}] ") for _, label, shortcut in actions) + 2 * (len(actions) - 1)
        start_x = max(2, (w - total_button_len) // 2)
        x = start_x
        for idx, (name, label, shortcut) in enumerate(actions):
            text = f" {label} [{shortcut}] "
            button_attr = attr("button", curses.A_BOLD)
            if mode == "actions" and idx == action_index:
                button_attr = attr("selected", curses.A_BOLD)
            try:
                stdscr.addstr(button_y, x, text[: max(0, w - x - 1)], button_attr)
            except curses.error:
                pass
            x += len(text) + 2

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
        win_w = min(80, max(40, w - 6))
        win_h = 9
        win_y = max(2, (h - win_h) // 2)
        win_x = max(2, (w - win_w) // 2)
        win = curses.newwin(win_h, win_w, win_y, win_x)
        win.bkgd(' ', attr("background"))
        win.erase()
        draw_border(win)

        help_lines = wrap(FIELD_HELP.get(key, ""), win_w - 4)
        try:
            win.addstr(1, 2, prompt, curses.A_BOLD)
            for offset, line in enumerate(help_lines[:2]):
                win.addstr(2 + offset, 2, line, attr("info"))
            win.addstr(4, 2, "Value:", curses.A_BOLD)
            current_value = str(cfg.get(key, ""))
            win.addstr(5, 2, current_value)
            win.clrtoeol()
        except curses.error:
            pass
        win.refresh()

        curses.echo()
        try:
            win.move(5, 2)
            new_value = win.getstr(5, 2, win_w - 4).decode("utf-8").strip()
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
            problems = _validate(cfg)
            if problems:
                set_status("; ".join(problems)[:120], "error")
                return None
            config = Config(
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
            save_config(config, DEFAULT_CONFIG_PATH)
            summary = _run_post_install_checks()
            show_summary("Post install checks", summary)
            set_status(f"Configuration saved to {DEFAULT_CONFIG_PATH}", "success")
            draw()
            curses.napms(400)
            return 0
        if action == "cancel":
            set_status("Setup cancelled. No changes saved.")
            draw()
            curses.napms(300)
            return 1
        return None

    draw()
    while True:
        key = stdscr.getch()
        if key == curses.KEY_RESIZE:
            draw()
            continue
        if mode == "fields":
            if key in (curses.KEY_UP, ord('k')):
                field_index = (field_index - 1) % len(FIELDS)
            elif key in (curses.KEY_DOWN, ord('j')):
                field_index = (field_index + 1) % len(FIELDS)
            elif key in (curses.KEY_ENTER, 10, 13):
                edit_field(*FIELDS[field_index])
                draw()
                continue
            elif key == 9:  # Tab
                mode = "actions"
            elif key in (ord('d'), ord('D')):
                ip = cfg.get("game_server_ip", "").strip()
                if ip:
                    cidr = _autodetect_cidr(ip)
                    if cidr:
                        cfg["net_cidr"] = str(cidr)
                        set_status(f"CIDR auto-detected: /{cidr}", "success")
                    else:
                        set_status("CIDR auto-detect failed", "error")
                else:
                    set_status("Enter the game server IP before auto-detecting", "error")
            elif key in (ord('s'), ord('S')):
                result = handle_action("save")
                if result is not None:
                    return result
            elif key in (ord('q'), ord('Q')):
                result = handle_action("cancel")
                if result is not None:
                    return result
        else:
            if key in (curses.KEY_LEFT, ord('h')):
                action_index = (action_index - 1) % len(actions)
            elif key in (curses.KEY_RIGHT, ord('l')):
                action_index = (action_index + 1) % len(actions)
            elif key in (curses.KEY_ENTER, 10, 13):
                result = handle_action(actions[action_index][0])
                if result is not None:
                    return result
            elif key in (9, curses.KEY_UP, ord('k')):
                mode = "fields"
            elif key in (ord('s'), ord('S')):
                result = handle_action("save")
                if result is not None:
                    return result
            elif key in (ord('q'), ord('Q')):
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
        print("Curses unavailable - switching to basic mode.")
        defaults, _ = _initial_field_values()
        cfg = defaults.copy()

        def ask(field: str, label: str, default: str) -> str:
            value = input(f"{label} [{default}]: ").strip()
            return value or default

        cfg["game_server_ip"] = ask("game_server_ip", "Game Server IP", cfg["game_server_ip"])
        cfg["game_server_mac"] = ask(
            "game_server_mac",
            "Game Server MAC (AA:BB:CC:DD:EE:FF)",
            cfg["game_server_mac"] or "AA:BB:CC:DD:EE:FF",
        )
        cidr = _autodetect_cidr(cfg["game_server_ip"]) or cfg["net_cidr"]
        cfg["net_cidr"] = ask("net_cidr", "Network CIDR", str(cidr))
        cfg["mc_port"] = ask("mc_port", "Minecraft Port", cfg["mc_port"])
        cfg["mc_motd_idle"] = ask("mc_motd_idle", "Minecraft MOTD (idle)", cfg["mc_motd_idle"])
        cfg["mc_motd_starting"] = ask(
            "mc_motd_starting",
            "Minecraft MOTD (starting)",
            cfg["mc_motd_starting"],
        )
        cfg["mc_version_label"] = ask("mc_version_label", "Minecraft Version Label", cfg["mc_version_label"])
        cfg["satisfactory_ports"] = ask(
            "satisfactory_ports",
            "Satisfactory Ports (CSV)",
            cfg["satisfactory_ports"],
        )
        cfg["ping_interval_sec"] = ask(
            "ping_interval_sec",
            "Ping Interval",
            cfg["ping_interval_sec"],
        )
        cfg["ping_fail_threshold"] = ask(
            "ping_fail_threshold",
            "Ping Fail Threshold",
            cfg["ping_fail_threshold"],
        )

        problems = _validate(cfg)
        if problems:
            print("Errors:", "; ".join(problems))
            return 1

        config = Config(
            game_server_ip=cfg["game_server_ip"],
            game_server_mac=cfg["game_server_mac"],
            net_cidr=int(cfg["net_cidr"]),
            mc_port=int(cfg["mc_port"]),
            mc_motd_idle=cfg["mc_motd_idle"],
            mc_motd_starting=cfg["mc_motd_starting"],
            mc_version_label=cfg["mc_version_label"],
            satisfactory_ports=[
                int(port)
                for port in cfg["satisfactory_ports"].split(',')
                if port.strip()
            ],
            ping_interval_sec=int(cfg["ping_interval_sec"]),
            ping_fail_threshold=int(cfg["ping_fail_threshold"]),
        )
        save_config(config, DEFAULT_CONFIG_PATH)
        summary = _run_post_install_checks()
        print(f"Saved configuration to {DEFAULT_CONFIG_PATH}")
        for label, level, message in summary:
            prefix = {"success": "[OK]", "info": "[info]", "error": "[error]"}.get(level, "[info]")
            first_line = message.splitlines()[0] if message else ""
            print(f"{prefix} {label}: {first_line}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
