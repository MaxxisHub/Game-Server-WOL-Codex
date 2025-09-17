# WOL Proxy (Minecraft & Satisfactory)

A compact Wake-on-LAN orchestration layer designed for small Linux SBCs. The proxy temporarily assumes the game server’s address, responds to status probes, wakes the real machine when a player connects, and gracefully returns control as soon as the hardware is reachable again.

## Table of Contents
- [Highlights](#highlights)
- [Architecture Overview](#architecture-overview)
- [Supported Platforms](#supported-platforms)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Configuration Reference](#configuration-reference)
- [Daily Operations](#daily-operations)
- [Troubleshooting](#troubleshooting)
- [Development](#development)
- [License](#license)

## Highlights
- **Instant IP takeover** – adds the configured server IP as a secondary address and advertises it via gratuitous ARP for a seamless hand-over.
- **Minecraft protocol shim** – serves the status/handshake/login packets, exposes configurable idle/starting MOTDs, version label and sends a friendly disconnect message during warm-up.
- **Satisfactory trigger** – listens on the default UDP query ports (`15000/15777/7777`) and wakes the real host when the server browser hits the proxy.
- **Broadcast-aware WOL** – discovers valid broadcast addresses for the interface and fans out the WOL magic packet, logging each attempt.
- **Curses setup wizard** – `wol-proxy-setup` guides you through the initial configuration, performs health checks and is safe to rerun at any time.
- **systemd integration** – installs as `wol-proxy.service`, restarts automatically after failures/power loss and emits verbose logs through `journalctl`.
- Zero third-party Python dependencies; everything runs with the standard library plus common networking tools.

## Architecture Overview
1. `wol-proxy.service` starts on boot and waits until `/opt/wol-proxy/config.json` exists (launch the wizard with `sudo wol-proxy-setup`).
2. When the real server is offline, the proxy claims the configured IP, answers Minecraft and Satisfactory probes, and keeps the idle MOTD visible.
3. A Minecraft login attempt or Satisfactory query triggers Wake-on-LAN. The proxy immediately releases the IP, allowing the real machine to take over, and switches the MOTD to “starting”.
4. A watchdog keeps pinging the true host. If it fails again later, the proxy instantly reclaims the IP – no more waiting for the full failure threshold.

## Supported Platforms
- Tested on Armbian/Debian-like distributions running on ARM single-board computers such as the ASUS Tinker Board S.
- Should work on any modern Linux with `systemd`, `ip`, `arping`, `ping`, `curl`, and Python 3.9 or newer.

## Prerequisites
The installer ensures the following packages are present (`apt-get install`):
- `python3`, `python3-venv`
- `iproute2`, `iputils-ping`, `arping`
- `curl`

Ensure your physical game server allows Wake-on-LAN in BIOS/NIC settings.

## Quick Start
```bash
git clone https://github.com/MaxxisHub/Game-Server-WOL-Codex.git
cd Game-Server-WOL-Codex
chmod +x install.sh
sudo ./install.sh
```
> **Tip:** Whenever you pull updates, rerun `sudo ./install.sh`. The script resynchronises `/opt/wol-proxy`, refreshes the systemd unit and restarts the service.

### Setup Wizard
```bash
sudo wol-proxy-setup
```
The TUI collects:
- Game server IPv4 and MAC addresses
- Minecraft port, idle/startup MOTDs, version label
- Satisfactory UDP ports
- Optional subnet CIDR detection (`D`) or manual entry

Saving writes `/opt/wol-proxy/config.json`, restarts the daemon and displays a post-install checklist (service status, enablement, last logs).

## Configuration Reference
`/opt/wol-proxy/config.json` (created by the wizard) contains:

| Field | Description |
| --- | --- |
| `game_server_ip` | IPv4 address normally owned by the real host. The proxy claims it when the host sleeps. |
| `game_server_mac` | MAC address used for Wake-on-LAN (format `AA:BB:CC:DD:EE:FF`). |
| `net_cidr` | Subnet size. Press `D` in the wizard to detect it automatically. |
| `mc_port` | Minecraft TCP status/login port (default `25565`). |
| `mc_motd_idle` | MOTD shown while the proxy controls the IP (e.g. `Join to start Server`). |
| `mc_motd_starting` | MOTD shown right after a wake trigger. |
| `mc_version_label` | Version string on the right side of the Minecraft server list. |
| `satisfactory_ports` | Array of UDP ports that should trigger WOL (default `[15000,15777,7777]`). |
| `ping_interval_sec` | Interval between reachability checks while the real server is online. |
| `ping_fail_threshold` | Consecutive failed pings before we assume the host went down (the first failure already triggers takeover if the proxy is idle). |

Edit the file manually if needed and restart the daemon: `sudo systemctl restart wol-proxy`.

## Daily Operations
```bash
sudo systemctl status wol-proxy       # view service state
sudo journalctl -u wol-proxy -n 50    # tail recent events
sudo systemctl restart wol-proxy      # apply config changes
```
Minecraft clients should always see `mc_motd_idle` while the proxy owns the IP. After a wake trigger you will see `mc_motd_starting` until the real host responds.

## Troubleshooting
- Review the logs: `sudo journalctl -u wol-proxy -n 100 --no-pager`
- Confirm WOL reachability manually: `sudo etherwake <MAC>` or `python3 -c 'from wol_proxy.wol import send_magic_packet; send_magic_packet("AA:BB:CC:DD:EE:FF")'`
- Ensure the real server is powered off when the proxy claims the IP to avoid ARP battles.
- If Minecraft displays “can’t connect”, verify the proxy listens on `mc_port` (`sudo ss -ltnp | grep mc_port`) and that no firewall blocks the response path.

## Development
```bash
# Run the proxy in foreground mode with a local config
sudo python3 -m src.wol_proxy.main --foreground --config ./config.json

# Validate shell scripts
bash -n install.sh

# Compile Python modules to catch syntax errors
python -m compileall src/wol_proxy
```
Pull requests are welcome. Please include a short description, your test steps, and keep the codebase dependency-free.

## License
Licensed under the [MIT License](LICENSE).
