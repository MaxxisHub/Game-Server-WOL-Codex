# WOL Proxy for Game Servers (Minecraft & Satisfactory)

## Overview
- Goal: Lightweight, robust WOL proxy for ARM single-board computers (e.g. ASUS Tinker Board S with Armbian) that temporarily takes over the IP of your real game server, intercepts Minecraft/Satisfactory traffic, wakes the real server via Wake-on-LAN, and hands the IP back once the host is up.
- Behaviour:
  - When the real server is down: the board takes over the server IP and listens on the configured ports.
  - Satisfactory: wakes the server as soon as the server browser triggers a UDP query.
  - Minecraft: wakes only after a real join attempt. The proxy shows a configurable MOTD (for example `Join to start Server`). When a join packet is seen the MOTD switches to `Starting`. Clients are disconnected with a friendly message: `Server is starting, please try again in 60 seconds`.
  - After sending the WOL packet the IP is released immediately so the real server can claim it.
  - While the real server is running, the proxy pings periodically. If the server later goes down, the board takes over the IP again and resumes listening.
- Resources: Minimal (Python 3, no third-party Python deps), ships with a systemd service.

## Features
- IP takeover via `ip addr add/del` and ARP announcement (`arping`) for clean failover.
- Wake-on-LAN magic packet broadcast using the configured MAC address.
- Minimal Minecraft protocol support for status/handshake/login-disconnect to expose MOTDs and block joins gracefully.
- Satisfactory trigger over UDP ports (default 15000/15777/7777). Any query starts the server.
- Automatic detection of the network interface for the target IP.
- Simple first-run web UI (local mini GUI) on port 8090 when no configuration is present.
- systemd unit for automatic start after a power loss.

## Supported Platforms
- Tested on Armbian/Debian-like systems running on ARM SBCs (e.g. ASUS Tinker Board S). Should generally work on Linux.

## Quickstart
1. Installation
   - Requirements: root/systemd privileges, internet access for package installation, Git.
   - Clone and install:
     ```bash
     git clone https://github.com/MaxxisHub/Game-Server-WOL-Codex.git
     cd Game-Server-WOL-Codex
     chmod +x install.sh
     sudo ./install.sh
     ```
     > **Note:** Run the installer from the repository root. If you renamed the folder, adjust the `cd` command accordingly.

2. Initial setup (terminal wizard)
   - After installation a curses TUI starts automatically.
   - Run manually at any time:
     ```bash
     sudo wol-proxy-setup
     ```
   - You will be asked for:
     - Game server IP (e.g. 192.168.1.50) and MAC (for WOL)
     - Minecraft port (default 25565) and MOTD texts
     - Satisfactory ports (default 15000/15777/7777)
     - Optional: Detect CIDR automatically (press `d`) or provide manually
   - Saving the wizard writes `/opt/wol-proxy/config.json` and restarts the daemon.

3. Manage the service
   ```bash
   sudo systemctl status wol-proxy
   sudo systemctl restart wol-proxy
   sudo journalctl -u wol-proxy -f
   ```

## Configuration
- File: `/opt/wol-proxy/config.json` (created/updated by the wizard). Example:
  ```json
  {
    "game_server_ip": "192.168.1.50",
    "game_server_mac": "AA:BB:CC:DD:EE:FF",
    "net_cidr": 24,
    "mc_port": 25565,
    "mc_motd_idle": "Join to start Server",
    "mc_motd_starting": "Starting...",
    "mc_version_label": "Offline",
    "satisfactory_ports": [15000, 15777, 7777],
    "ping_interval_sec": 3,
    "ping_fail_threshold": 10
  }
  ```
- `net_cidr` is usually detected automatically. Adjust for exotic networks if required.

## How It Works
1. systemd starts the daemon.
2. If `config.json` is missing the daemon waits for configuration (start the TUI with `sudo wol-proxy-setup`).
3. With configuration present:
   - Check if the real game server is reachable (ping/TCP).
   - If not reachable:
     - Take over the server IP (secondary address) on the detected interface and announce via ARP.
     - Start listeners:
       - Minecraft TCP: replies to status pings with MOTD/version, triggers WOL on login attempts, disconnects the client politely, releases the IP immediately.
       - Satisfactory UDP: any query triggers WOL and releases the IP immediately.
   - While in the starting phase the daemon polls until the real server is up. Once reachable the proxy stays idle and the IP remains released.
   - If the server later goes down (consecutive ping failures) the proxy reclaims the IP and resumes listening.

## Security & Notes
- The daemon manages IP addresses and privileged ports; it must run as root. Code is minimal and logs key actions.
- Wake-on-LAN requires BIOS/NIC support on the game server.
- Ensure the real server is powered off when taking over the IP to avoid conflicts.

## Uninstall
```bash
sudo ./uninstall.sh
```

## Development
- Source code lives in `src/wol_proxy`. No external Python dependencies.
- Run locally (without systemd) for tests:
  ```bash
  sudo python3 -m src.wol_proxy.main --foreground --config ./config.json
  ```

## License
- Add a license if required. Currently unlicensed.
